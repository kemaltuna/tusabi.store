"use client"

import { useQuery, useQueryClient } from "@tanstack/react-query"
import { fetchNextCard } from "../../lib/api"
import { QuizCardData } from "../../lib/types"
import { QuizCard } from "../../components/QuizCard"
import { QuizLibrarySidebar } from "../../components/QuizLibrarySidebar"
import { GenerationSidebar } from "../../components/GenerationSidebar"
import { GenerationControls } from "../../components/GenerationControls"
import GenerationStatusPanel from "../../components/GenerationStatusPanel"
import { AutoChunkModal } from "../../components/AutoChunkModal"
import { QuizModeSelector, QuizMode } from "../../components/QuizModeSelector"
import { StudySidebar } from "../../components/StudySidebar"
import { useState, useEffect, useRef, type PointerEvent as ReactPointerEvent } from "react"
import { useRouter } from "next/navigation"
import { RefreshCw, LogOut, User, Menu, X, Sparkles, BookOpen, Highlighter, PanelRight } from "lucide-react"
import { useAuth } from "../../lib/auth"
import { cn } from "../../lib/utils"

interface SelectedPdf {
    title: string
    file: string
    pageCount: number
    source: string  // e.g., "Anatomi", "Farmakoloji"
    mainHeader?: string // The main topic/category key
    existingQuestionCount?: number
    sourcePdfsList?: string[]
    mergedTopics?: string[]
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "/api"

async function parseApiError(response: Response, fallback: string): Promise<string> {
    const contentType = response.headers.get("content-type") || ""

    if (contentType.includes("application/json")) {
        try {
            const data = await response.json()
            if (typeof data?.detail === "string" && data.detail.trim()) return data.detail
            if (typeof data?.message === "string" && data.message.trim()) return data.message
        } catch {
            // fall back to text payload parsing
        }
    }

    try {
        const text = (await response.text()).trim()
        if (text) return text
    } catch {
        // ignore parse failure
    }

    return fallback
}

export default function DashboardPage() {
    const queryClient = useQueryClient()
    const [selectedTopic, setSelectedTopic] = useState<string | undefined>(undefined)
    const [selectedSource, setSelectedSource] = useState<string | undefined>(undefined)
    const [selectedCategory, setSelectedCategory] = useState<string | undefined>(undefined)
    const [isQuizActive, setIsQuizActive] = useState(false)
    const [mode, setMode] = useState<QuizMode>("standard")
    const [sidebarOpen, setSidebarOpen] = useState(true)
    const [rightSidebarOpen, setRightSidebarOpen] = useState(true)
    const [isDesktop, setIsDesktop] = useState(false)
    const [activeView, setActiveView] = useState<'library' | 'flashcards' | 'generation'>('library')
    // const [generationMode, setGenerationMode] = useState(false) // Replaced by activeView
    const [selectedPdfs, setSelectedPdfs] = useState<SelectedPdf[]>([])
    const [isGenerating, setIsGenerating] = useState(false)
    const [generationResult, setGenerationResult] = useState<string | null>(null)
    const [generationQuestionIds, setGenerationQuestionIds] = useState<number[]>([])
    const [generationDownloadUrl, setGenerationDownloadUrl] = useState<string | null>(null)
    // const [flashcardMode, setFlashcardMode] = useState(false) // Replaced by activeView
    const [flashcardLimit, setFlashcardLimit] = useState(30)
    const [isFlashcardGenerating, setIsFlashcardGenerating] = useState(false)
    const [flashcardResult, setFlashcardResult] = useState<string | null>(null)
    const [sidebarWidth, setSidebarWidth] = useState(320)
    const [touchStart, setTouchStart] = useState<number | null>(null)
    const [isResizing, setIsResizing] = useState(false)
    const sidebarRef = useRef<HTMLDivElement>(null)
    const { user, logout, isLoading: authLoading } = useAuth()
    const router = useRouter()

    // Auto-Chunk Modal State
    const [autoChunkOpen, setAutoChunkOpen] = useState(false)
    const [autoChunkSegmentTitle, setAutoChunkSegmentTitle] = useState("")
    const [autoChunkSource, setAutoChunkSource] = useState("")
    const [autoChunkSubSegments, setAutoChunkSubSegments] = useState<{ title: string; file: string; page_count: number; source_pdfs_list?: string[]; merged_topics?: string[] }[]>([])
    const [autoChunkTotalPages, setAutoChunkTotalPages] = useState(0)

    const [currentCard, setCurrentCard] = useState<any | null>(null)
    const [loading, setLoading] = useState(false)
    const [history, setHistory] = useState<QuizCardData[]>([]) // History stack

    useEffect(() => {
        return () => {
            if (generationDownloadUrl) {
                URL.revokeObjectURL(generationDownloadUrl)
            }
        }
    }, [generationDownloadUrl])


    // Redirect to login if not authenticated
    useEffect(() => {
        if (!authLoading && !user) {
            router.push("/login")
        }
    }, [authLoading, user, router])

    useEffect(() => {
        if (user && user.role !== "admin" && mode === "latest") {
            setMode("standard")
        }
    }, [user, mode])

    useEffect(() => {
        if (typeof window === "undefined") return
        const mediaQuery = window.matchMedia("(min-width: 1024px)")
        const legacyMediaQuery = mediaQuery as MediaQueryList & {
            addListener?: (listener: (event: MediaQueryListEvent) => void) => void
            removeListener?: (listener: (event: MediaQueryListEvent) => void) => void
        }

        const handleChange = () => {
            const desktop = mediaQuery.matches
            setIsDesktop(desktop)
            if (desktop) {
                // Keep current state on desktop so user can collapse manually.
            } else {
                setSidebarOpen(false)
                setRightSidebarOpen(false)
            }
        }

        handleChange()
        if (typeof mediaQuery.addEventListener === "function") {
            mediaQuery.addEventListener("change", handleChange)
        } else if (typeof legacyMediaQuery.addListener === "function") {
            legacyMediaQuery.addListener(handleChange)
        }

        return () => {
            if (typeof mediaQuery.removeEventListener === "function") {
                mediaQuery.removeEventListener("change", handleChange)
            } else if (typeof legacyMediaQuery.removeListener === "function") {
                legacyMediaQuery.removeListener(handleChange)
            }
        }
    }, [])

    const openLeftSidebar = () => {
        setSidebarOpen(true)
        if (!isDesktop) setRightSidebarOpen(false)
    }

    const openRightSidebar = () => {
        setRightSidebarOpen(true)
        if (!isDesktop) setSidebarOpen(false)
    }

    const closeSidebars = () => {
        setSidebarOpen(false)
        setRightSidebarOpen(false)
    }



    // Removed useQuery for next-card, now managed by local state and fetchNextCard function

    const startResizing = (e: React.MouseEvent) => {
        setIsResizing(true)
        e.preventDefault()
    }

    const stopResizing = () => {
        setIsResizing(false)
    }

    const resize = (e: MouseEvent) => {
        if (isResizing) {
            const newWidth = e.clientX
            if (newWidth > 240 && newWidth < 600) {
                setSidebarWidth(newWidth)
            }
        }
    }

    // Touch Gestures
    const handleTouchStart = (e: React.TouchEvent) => {
        setTouchStart(e.touches[0].clientX)
    }

    const handleTouchMove = (e: React.TouchEvent) => {
        if (touchStart === null) return

        const currentTouch = e.touches[0].clientX
        const diff = currentTouch - touchStart

        // Swipe Right to Open (Only if starting from left area in mobile - relaxed to 50%)
        // DISABLED per user request (Conflicts with highlighter)
        /*
        if (!isDesktop && !sidebarOpen && touchStart < window.innerWidth * 0.5 && diff > 50) {
            setSidebarOpen(true)
            setRightSidebarOpen(false)
            setTouchStart(null) // Reset
        }
        */

        // Swipe Left to Close (Only if sidebar is open)
        if (!isDesktop && sidebarOpen && diff < -50) {
            setSidebarOpen(false)
            setTouchStart(null) // Reset
        }
    }

    const handleTouchEnd = () => {
        setTouchStart(null)
    }

    useEffect(() => {
        window.addEventListener("mousemove", resize)
        window.addEventListener("mouseup", stopResizing)
        return () => {
            window.removeEventListener("mousemove", resize)
            window.removeEventListener("mouseup", stopResizing)
        }
    }, [isResizing])

    // Session Persistence
    useEffect(() => {
        const loadSession = async () => {
            const token = localStorage.getItem("medquiz_token")
            if (!token) return
            try {
                const res = await fetch(`${API_BASE}/quiz/session`, { headers: { Authorization: `Bearer ${token}` } })
                if (res.ok) {
                    const session = await res.json()
                    if (session.active_mode) setMode(session.active_mode)
                    if (session.active_topic || session.active_source || session.active_category) {
                        setSelectedTopic(session.active_topic)
                        setSelectedSource(session.active_source)
                        setSelectedCategory(session.active_category)
                        // Auto-resume if there was active context
                        setIsQuizActive(true)
                        // We fetch next card to resume
                        fetchNextCard(session.active_topic, session.active_source, session.active_category)
                    }
                }
            } catch (e) { console.error("Session load failed", e) }
        }
        loadSession()
    }, [])

    // Autosave Session
    useEffect(() => {
        if (!currentCard && !selectedTopic) return

        const saveTimer = setTimeout(() => {
            const token = localStorage.getItem("medquiz_token")
            if (!token) return

            fetch(`${API_BASE}/quiz/session`, {
                method: "POST",
                headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
                body: JSON.stringify({
                    active_page: "dashboard",
                    active_topic: selectedTopic,
                    active_source: selectedSource,
                    active_category: selectedCategory,
                    active_mode: mode,
                    current_card_id: currentCard?.id
                })
            }).catch(e => console.error("Session save failed", e))
        }, 2000)

        return () => clearTimeout(saveTimer)
    }, [currentCard, mode, selectedTopic, selectedSource, selectedCategory])


    // Refetch card when Mode changes (Immediate Feedback)
    useEffect(() => {
        if (isQuizActive) {
            // Pass current selection to ensure context is maintained
            fetchNextCard(selectedTopic, selectedSource, selectedCategory)
        }
    }, [mode])


    const handleLogout = () => {
        logout()
        router.push("/login")
    }

    const handleTopicSelect = (topic: string | undefined, source?: string, category?: string) => {
        setSelectedTopic(topic)
        setSelectedSource(source)
        setSelectedCategory(category)
        if (topic || source || category) {
            startQuiz(topic, source, category)
        } else {
            setIsQuizActive(false)
        }
    }

    const startQuiz = (topic?: string, source?: string, category?: string, modeOverride?: QuizMode) => {
        // Reset current card when switching topics/modes
        setCurrentCard(null)
        setHistory([]) // Clear history on new quiz
        setIsQuizActive(true)
        fetchNextCard(topic, source, category, modeOverride)
    }

    const fetchNextCard = async (topic?: string, source?: string, category?: string, modeOverride?: QuizMode) => {
        setLoading(true)
        try {
            const token = localStorage.getItem("medquiz_token")
            if (!token) return

            const effectiveMode = modeOverride ?? mode
            let url = `${API_BASE}/quiz/next?mode=${effectiveMode}`
            if (topic) url += `&topic=${encodeURIComponent(topic)}`
            if (source) url += `&source=${encodeURIComponent(source)}`
            if (category) url += `&category=${encodeURIComponent(category)}`

            const res = await fetch(url, {
                headers: { Authorization: `Bearer ${token}` }
            })

            if (!res.ok) {
                throw new Error("Failed to fetch next card")
            }
            const data = await res.json()

            // Push current to history if exists (and different)
            if (currentCard) {
                setHistory(prev => [...prev, currentCard])
            }
            setCurrentCard(data?.card ?? data)
        } catch (error) {
            console.error("Error fetching next card:", error)
            setCurrentCard(null) // Clear card on error
        } finally {
            setLoading(false)
        }
    }

    const handleAdminLatestSelect = () => {
        const nextMode: QuizMode = mode === "latest" ? "standard" : "latest"
        setMode(nextMode)
        setSelectedTopic(undefined)
        setSelectedSource(undefined)
        setSelectedCategory(undefined)
        startQuiz(undefined, undefined, undefined, nextMode)
    }



    const handleGenerate = async (count: number, difficulty: number, customPromptSections?: Record<string, string> | null, customDifficultyLevels?: Record<string, string> | null) => {
        if (selectedPdfs.length === 0) return

        setIsGenerating(true)
        setGenerationResult(null)
        setGenerationQuestionIds([])
        setGenerationDownloadUrl(null)

        try {
            // Build payload with correct source and PDF paths
            const token = localStorage.getItem("medquiz_token")

            // Get source from first selected PDF (all should be from same source)
            const source_material = selectedPdfs[0].source

            // Build list of all selected topics and PDF paths
            const mergedTopics = selectedPdfs.flatMap(p => p.mergedTopics || [])
            const mergedPdfList = selectedPdfs.flatMap(p => p.sourcePdfsList || [])
            const all_topics = mergedTopics.length > 0 ? mergedTopics : selectedPdfs.map(p => p.title)
            const source_pdfs_list = mergedPdfList.length > 0
                ? Array.from(new Set(mergedPdfList))
                : selectedPdfs.map(p => p.file)

            const genRes = await fetch(`${API_BASE}/admin/generate`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    ...(token ? { Authorization: `Bearer ${token}` } : {})
                },
                body: JSON.stringify({
                    topic: selectedPdfs[0].title,
                    source_material: source_material,
                    main_header: selectedPdfs[0].mainHeader, // Pass the Strict Scope Main Header
                    count: count,
                    difficulty: difficulty,
                    all_topics: all_topics,
                    source_pdfs_list: source_pdfs_list.length > 1 ? source_pdfs_list : null,
                    custom_prompt_sections: customPromptSections || null,
                    custom_difficulty_levels: customDifficultyLevels || null
                })
            })

            if (!genRes.ok) {
                const message = await parseApiError(genRes, "Generation failed")
                throw new Error(message)
            }

            const result = await genRes.json()
            const statusIcon = "🚀"

            // Async Response Handling
            setGenerationResult(`${statusIcon} ${result.message}`)
            setGenerationQuestionIds([])
            setGenerationDownloadUrl(null)

            // Clear selection after success
            setTimeout(() => {
                setSelectedPdfs([])
            }, 2000)

        } catch (error: any) {
            setGenerationResult(`❌ Hata: ${error.message}`)
            setGenerationQuestionIds([])
            setGenerationDownloadUrl(null)
        } finally {
            setIsGenerating(false)
        }
    }

    const handleGenerateFlashcards = async () => {
        setIsFlashcardGenerating(true)
        setFlashcardResult(null)

        try {
            const token = localStorage.getItem("medquiz_token")
            if (!token) {
                throw new Error("Giriş yapılmadı.")
            }

            const res = await fetch(`${API_BASE}/flashcards/generate`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    Authorization: `Bearer ${token}`
                },
                body: JSON.stringify({
                    limit: flashcardLimit,
                    max_cards: flashcardLimit
                })
            })

            if (!res.ok) {
                const error = await res.json().catch(() => ({}))
                throw new Error(error.detail || "Flashcard üretilemedi.")
            }

            const result = await res.json()
            setFlashcardResult(`✅ ${result.created} flashcard üretildi (${result.highlight_count} highlight).`)
        } catch (error: any) {
            setFlashcardResult(`❌ Hata: ${error.message}`)
        } finally {
            setIsFlashcardGenerating(false)
        }
    }

    if (authLoading) {
        return (
            <div className="min-h-screen bg-zinc-50 dark:bg-black flex items-center justify-center">
                <RefreshCw className="w-8 h-8 animate-spin text-blue-500" />
            </div>
        )
    }

    if (!user) return null

    const sidebarWidthStyle = !sidebarOpen && isDesktop ? "0px" : "fit-content"
    const sidebarMinWidthStyle = !sidebarOpen && isDesktop ? "0px" : "320px"
    const sidebarMaxWidthStyle = isDesktop ? (sidebarOpen ? "600px" : "0px") : "85vw"

    return (
        <div
            className="h-[100dvh] w-full bg-[var(--page-background)] text-[var(--foreground)] flex overflow-hidden"
            onTouchStart={handleTouchStart}
            onTouchMove={handleTouchMove}
            onTouchEnd={handleTouchEnd}
        >
            {/* Mobile Sidebar Toggle - (Same logic) */}
            <button
                className="fixed top-4 left-4 z-[200] p-2 bg-white dark:bg-zinc-800 rounded-lg shadow-lg"
                onClick={() => {
                    const next = !sidebarOpen
                    setSidebarOpen(next)
                    if (next && !isDesktop) setRightSidebarOpen(false)
                }}
            >
                {sidebarOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
            </button>

            <button
                className="fixed top-4 right-4 z-[200] p-2 bg-white dark:bg-zinc-800 rounded-lg shadow-lg"
                onClick={() => {
                    const next = !rightSidebarOpen
                    setRightSidebarOpen(next)
                    if (next && !isDesktop) setSidebarOpen(false)
                }}
                title="Etut Paneli"
            >
                {rightSidebarOpen ? <X className="w-5 h-5" /> : <PanelRight className="w-5 h-5" />}
            </button>



            {/* Sidebar */}
            <div
                className={cn(
                    "fixed lg:static inset-y-0 left-0 z-[100] shrink-0 order-1 h-full",
                    "transform transition-transform duration-300 ease-in-out motion-reduce:transition-none",
                    sidebarOpen ? "translate-x-0 lg:w-auto lg:overflow-visible lg:pointer-events-auto" : "-translate-x-full lg:w-0 lg:overflow-hidden lg:pointer-events-none"
                )}
            >
                <div
                    className={cn(
                        "relative h-full liquid-glass border-r border-white/60 dark:border-zinc-700/40 shadow-2xl transition-[width] ease-linear duration-0 flex flex-col overflow-hidden",
                        sidebarOpen ? "" : "lg:w-0 lg:min-w-0 lg:max-w-0"
                    )}
                    style={{
                        width: sidebarWidthStyle,
                        minWidth: sidebarMinWidthStyle,
                        maxWidth: sidebarMaxWidthStyle
                    }}
                >
                    <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(255,255,255,0.7),transparent_60%)] opacity-70" />

                    {/* Drag Handle */}
                    <div
                        className="absolute top-0 -right-2 w-4 h-full cursor-col-resize z-[150] group/handle flex justify-center"
                        onMouseDown={startResizing}
                    >
                        <div className="w-[2px] h-full bg-zinc-300 dark:bg-zinc-700 opacity-0 group-hover/handle:opacity-100 group-hover/handle:bg-blue-500 transition-all" />
                    </div>

                    <div className="relative h-full flex flex-col">
                        {/* Sidebar Header */}
                        <div className="p-4 pt-6 pb-2 space-y-4">
                            <h1 className="text-2xl font-bold bg-gradient-to-r from-blue-600 to-purple-600 bg-clip-text text-transparent">
                                TUSabi
                            </h1>

                            {/* Navigation Buttons */}
                            <div className="flex flex-col gap-1">
                                <button
                                    onClick={() => setActiveView('library')}
                                    className={cn(
                                        "flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors w-full text-left",
                                        activeView === 'library'
                                            ? "bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400"
                                            : "text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                                    )}
                                >
                                    <BookOpen className="w-4 h-4" />
                                    <span>Kütüphane</span>
                                </button>
                                <button
                                    onClick={() => {
                                        setActiveView('library')
                                        handleTopicSelect(undefined, 'AI Flashcards', undefined)
                                    }}
                                    className={cn(
                                        "flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors w-full text-left",
                                        (activeView === 'library' && selectedSource === 'AI Flashcards')
                                            ? "bg-amber-50 dark:bg-amber-900/20 text-amber-600 dark:text-amber-400"
                                            : "text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                                    )}
                                >
                                    <Highlighter className="w-4 h-4" />
                                    <span>AI Flashcards</span>
                                </button>
                            </div>
                        </div>
                        <div className="flex-1 overflow-y-auto no-scrollbar">
                            {activeView === 'generation' ? (
                                <GenerationSidebar
                                    onSelectionChange={setSelectedPdfs}
                                    selectedPdfs={selectedPdfs}
                                    onAutoChunkRequest={(segTitle, src, subSegs, totalPgs) => {
                                        setAutoChunkSegmentTitle(segTitle)
                                        setAutoChunkSource(src)
                                        setAutoChunkSubSegments(subSegs)
                                        setAutoChunkTotalPages(totalPgs)
                                        setAutoChunkOpen(true)
                                    }}
                                />
                            ) : activeView === 'library' ? (
                                <QuizLibrarySidebar
                                    onTopicSelect={handleTopicSelect}
                                    selectedTopic={selectedTopic}
                                    selectedSource={selectedSource}
                                    selectedCategory={selectedCategory}
                                    showAdminLatest={user?.role === "admin"}
                                    isLatestActive={mode === "latest"}
                                    onAdminLatestSelect={handleAdminLatestSelect}
                                />
                            ) : null}
                        </div>
                    </div>
                </div>
            </div>

            <div
                className={cn(
                    "fixed lg:static inset-y-0 right-0 z-[100] shrink-0 order-3 h-full",
                    "transform transition-transform duration-300 ease-in-out motion-reduce:transition-none",
                    rightSidebarOpen ? "translate-x-0 lg:w-auto lg:overflow-visible lg:pointer-events-auto" : "translate-x-full lg:w-0 lg:overflow-hidden lg:pointer-events-none"
                )}
            >
                <div
                    className={cn(
                        "relative h-full w-[85vw] sm:w-80 liquid-glass border-l border-white/60 dark:border-zinc-700/40 shadow-2xl flex flex-col",
                        rightSidebarOpen ? "" : "lg:w-0 lg:min-w-0 lg:max-w-0"
                    )}
                >
                    <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_right,rgba(255,255,255,0.7),transparent_60%)] opacity-70" />
                    <div className="relative flex-1 overflow-y-auto no-scrollbar">
                        <StudySidebar />
                    </div>
                </div>
            </div>

            {/* Overlay for mobile */}
            {!isDesktop && (sidebarOpen || rightSidebarOpen) && (
                <div
                    className="fixed inset-0 bg-black/50 z-30 lg:hidden"
                    onClick={closeSidebars}
                />
            )}

            {/* Main Content - Scrollable Area */}
            {/* Main Content - Scrollable Area */}
            {/* Added no-scrollbar to hide ugly bars */}
            <div className="flex-1 flex flex-col h-full overflow-y-auto order-2 min-w-0 relative scroll-smooth no-scrollbar pb-64">
                {/* Header */}
                <header className="sticky top-0 z-20 bg-white/80 dark:bg-zinc-900/80 backdrop-blur border-b border-zinc-200 dark:border-zinc-800 p-4 flex justify-between items-center min-w-0">
                    <div className="flex items-center gap-3 ml-12 lg:ml-0 flex-1 min-w-0">

                        <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 overflow-x-auto whitespace-nowrap touch-pan-x no-scrollbar pr-2">
                                {user?.role === "admin" && (
                                    <>
                                        {/* Generation Mode Toggle */}
                                        <button
                                            onClick={() => {
                                                const next = activeView !== 'generation'
                                                if (next) {
                                                    setActiveView('generation')
                                                    {/* Reset states usually handled by mode switch */ }
                                                    setFlashcardResult(null)
                                                    setSelectedPdfs([])
                                                    setGenerationResult(null)
                                                } else {
                                                    setActiveView('library')
                                                }
                                            }}
                                            className={cn(
                                                "flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition-all shrink-0",
                                                activeView === 'generation'
                                                    ? "bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300"
                                                    : "bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200 dark:hover:bg-zinc-700"
                                            )}
                                        >
                                            {activeView === 'generation' ? (
                                                <>
                                                    <BookOpen className="w-4 h-4" />
                                                    Quiz Modu
                                                </>
                                            ) : (
                                                <>
                                                    <Sparkles className="w-4 h-4" />
                                                    Üretim Modu
                                                </>
                                            )}
                                        </button>


                                    </>
                                )}

                                {activeView === 'library' && (
                                    <>
                                        <QuizModeSelector
                                            mode={mode}
                                            onChange={setMode}
                                            className="shrink-0"
                                            showLatest={user?.role === "admin"}
                                        />
                                        {(selectedTopic || selectedSource || selectedCategory) && (
                                            <span className="text-sm text-zinc-500 bg-zinc-100 dark:bg-zinc-800 px-3 py-1 rounded-full shrink-0">
                                                {selectedTopic || selectedCategory || selectedSource}
                                            </span>
                                        )}
                                    </>
                                )}

                                {/* User / Admin & Logout Controls - Moved to swipeable bar */}
                                <div className="h-6 w-px bg-zinc-300 dark:bg-zinc-700 mx-2 shrink-0" />

                                <div className="flex items-center gap-2 text-sm text-zinc-500 dark:text-zinc-400 shrink-0 bg-zinc-100 dark:bg-zinc-800 py-1 px-3 rounded-full">
                                    <User className="w-4 h-4" />
                                    <span className="hidden sm:inline">{user.username}</span>
                                    {user.role === "admin" && (
                                        <button
                                            onClick={() => router.push('/admin')}
                                            className="bg-purple-500/10 hover:bg-purple-500/20 text-purple-600 dark:text-purple-400 px-2 py-1 rounded-lg text-xs font-medium transition-colors flex items-center gap-1"
                                            title="Admin Paneline Git"
                                        >
                                            <span className="bg-purple-500 w-1.5 h-1.5 rounded-full animate-pulse" />
                                            Admin Panel
                                        </button>
                                    )}
                                </div>
                                <button
                                    onClick={handleLogout}
                                    className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium bg-red-50 text-red-600 dark:bg-red-900/20 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-900/30 transition-colors shrink-0"
                                    title="Çıkış Yap"
                                >
                                    <LogOut className="w-4 h-4" />
                                    <span className="hidden sm:inline">Çıkış</span>
                                </button>
                            </div>
                        </div>
                    </div>

                    <div className="hidden"> {/* Previously User/Logout section, hidden/removed */}
                        <div className="flex items-center gap-2 text-sm text-zinc-500 dark:text-zinc-400">
                            <User className="w-4 h-4" />
                            <span className="hidden sm:inline">{user.username}</span>
                            {user.role === "admin" && (
                                <span className="bg-purple-500/20 text-purple-400 px-2 py-0.5 rounded text-xs">Admin</span>
                            )}
                        </div>
                        <button
                            onClick={handleLogout}
                            className="p-2 text-zinc-500 hover:text-red-500 transition-colors"
                            title="Çıkış Yap"
                        >
                            <LogOut className="w-5 h-5" />
                        </button>
                    </div>
                </header>

                {/* Main Area */}
                {/* Removed pb-64 from here, added to parent div */}
                <main className="flex-1 flex flex-col items-center p-4 md:p-8">
                    {activeView === 'generation' ? (
                        /* Generation Mode UI */
                        <div className="w-full max-w-xl space-y-4 my-auto">
                            <GenerationControls
                                selectedPdfs={selectedPdfs}
                                onGenerate={handleGenerate}
                                onClear={() => {
                                    setSelectedPdfs([])
                                    setGenerationResult(null)
                                }}
                                isGenerating={isGenerating}
                            />

                            {generationResult && (
                                <div className={cn(
                                    "p-4 rounded-lg text-center",
                                    generationResult.startsWith("✅")
                                        ? "bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-300"
                                        : "bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300"
                                )}>
                                    {generationResult}
                                </div>
                            )}

                            {generationQuestionIds.length > 0 && (
                                <div className="p-4 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900">
                                    <div className="text-xs font-semibold text-zinc-500 mb-2">Üretilen Soru ID’leri</div>
                                    <div className="text-sm text-zinc-700 dark:text-zinc-200 break-words">
                                        {generationQuestionIds.join(", ")}
                                    </div>
                                    {generationDownloadUrl && (
                                        <a
                                            className="inline-flex mt-3 text-sm text-blue-600 hover:text-blue-700"
                                            href={generationDownloadUrl}
                                            download={`generated_questions_${Date.now()}.json`}
                                        >
                                            JSON indir
                                        </a>
                                    )}
                                </div>
                            )}

                            <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-4 shadow-sm">
                                <GenerationStatusPanel />
                            </div>

                        </div>
                    ) : (
                        /* Quiz Mode UI */
                        <>
                            {loading ? (
                                <div className="flex flex-col items-center justify-center py-20 animate-pulse text-zinc-400 my-auto">
                                    <RefreshCw className="w-8 h-8 animate-spin mb-4" />
                                    <p>Yükleniyor...</p>
                                </div>
                            ) : !isQuizActive && !currentCard ? (
                                <div className="text-center py-20 text-zinc-500 my-auto">
                                    <BookOpen className="w-12 h-12 mx-auto mb-4 opacity-20" />
                                    <p>Bir konu seçerek başlayın.</p>
                                </div>
                            ) : !currentCard ? (
                                <div className="text-center py-20 my-auto">
                                    <h2 className="text-xl font-semibold mb-2">🎉 Hepsini Bitirdin!</h2>
                                    <p className="text-zinc-500">
                                        Şu an için tekrar edilecek kart yok.
                                    </p>
                                    <button
                                        onClick={() => fetchNextCard(selectedTopic, selectedSource, selectedCategory)}
                                        className="mt-4 px-4 py-2 bg-zinc-200 dark:bg-zinc-800 rounded"
                                    >
                                        Yenile
                                    </button>
                                </div>
                            ) : (
                                <div className="max-w-3xl mx-auto w-full my-auto">
                                    <div className="mb-4 flex items-center justify-between">
                                        <button
                                            onClick={() => {
                                                setIsQuizActive(false)
                                                setCurrentCard(null)
                                                setSelectedTopic(undefined)
                                                setSelectedSource(undefined)
                                                setSelectedCategory(undefined)
                                            }}
                                            className="text-sm text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 flex items-center gap-1"
                                        >
                                            ← Kütüphaneye Dön
                                        </button>
                                    </div>
                                    <QuizCard
                                        card={currentCard}
                                        onNext={() => fetchNextCard(selectedTopic, selectedSource, selectedCategory)}
                                        onPrevious={history.length > 0 ? () => {
                                            const prev = history[history.length - 1]
                                            setHistory(h => h.slice(0, -1))
                                            setCurrentCard(prev)
                                        } : undefined}
                                    />
                                </div>
                            )}
                        </>
                    )}
                </main>
            </div >

            {/* Auto-Chunk Modal */}
            <AutoChunkModal
                isOpen={autoChunkOpen}
                onClose={() => setAutoChunkOpen(false)}
                segmentTitle={autoChunkSegmentTitle}
                source={autoChunkSource}
                subSegments={autoChunkSubSegments}
                totalPages={autoChunkTotalPages}
            />
        </div >
    )
}
