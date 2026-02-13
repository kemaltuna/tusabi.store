"use client"

import { useState, useEffect } from "react"
import { ChevronRight, ChevronDown, BookOpen, Folder, FileText, Play } from "lucide-react"
import { cn } from "../lib/utils"

interface TopicItem {
    topic: string
    count: number
    solved_count?: number
    is_category?: boolean
    is_generated?: boolean
    is_part?: boolean
    path?: string // for flashcards if needed
}

interface SubjectData {
    topic_count: number
    categories: Record<string, TopicItem[]>
}

interface FlashcardSourceData {
    categories?: Record<string, TopicItem[]>
}

interface QuizLibrarySidebarProps {
    onTopicSelect: (topic: string | undefined, source?: string, category?: string) => void
    selectedTopic?: string
    selectedSource?: string
    selectedCategory?: string
    showAdminLatest?: boolean
    isLatestActive?: boolean
    onAdminLatestSelect?: () => void
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "/api"

export function QuizLibrarySidebar({
    onTopicSelect,
    selectedTopic,
    selectedSource,
    selectedCategory,
    showAdminLatest = false,
    isLatestActive = false,
    onAdminLatestSelect
}: QuizLibrarySidebarProps) {
    const [library, setLibrary] = useState<Record<string, SubjectData>>({})
    const [loading, setLoading] = useState(true)
    const [expandedSubjects, setExpandedSubjects] = useState<Set<string>>(new Set())
    const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set())

    useEffect(() => {
        fetchLibrary()
    }, [])

    const fetchLibrary = async () => {
        try {
            // Fetch optimized tree from backend instead of raw manifests
            const token = localStorage.getItem("medquiz_token")
            const headers: Record<string, string> = {}
            if (token) headers.Authorization = `Bearer ${token}`

            const treeRes = await fetch(`${API_BASE}/library/tree`, { headers })
            const flashcardRes = await fetch(`${API_BASE}/library/flashcards`, { headers })

            let subjects: Record<string, SubjectData> = {}

            if (treeRes.ok) {
                subjects = await treeRes.json()
            }

            // Merge Flashcards
            if (flashcardRes.ok) {
                const fcData = await flashcardRes.json()
                // fcData: { SourceName: { categories: { "Flashcards": [...] } } }

                for (const [sourceName, sourceData] of Object.entries(fcData)) {
                    // Start or update subject
                    if (!subjects[sourceName]) {
                        subjects[sourceName] = { topic_count: 0, categories: {} }
                    }

                    const fcCategories = (sourceData as FlashcardSourceData).categories || {}
                    for (const [catName, topics] of Object.entries(fcCategories)) {
                        // Usually catName is "Flashcards"
                        // Append to existing categories
                        subjects[sourceName].categories[catName] = topics as TopicItem[]

                        // Note: topic_count in SubjectData is total topics? Or total questions?
                        // library.py: "topic_count": sum(len(v) for v in categories_output.values()) -> This is number of NODES.
                        // Let's just track question count for display if we can, but library.py returns node count.
                        // The UI displays question count sum. We should recalculate it from categories for safety.
                    }
                }
            }

            setLibrary(subjects)
        } catch (error) {
            console.error("Failed to fetch library tree:", error)
        } finally {
            setLoading(false)
        }
    }

    const toggleSubject = (subject: string) => {
        setExpandedSubjects(prev => {
            const next = new Set(prev)
            if (prev.has(subject)) next.delete(subject)
            else next.add(subject)
            return next
        })
    }

    const toggleCategory = (key: string) => {
        setExpandedCategories(prev => {
            const next = new Set(prev)
            if (prev.has(key)) next.delete(key)
            else next.add(key)
            return next
        })
    }

    const handleCategoryClick = (source: string, category: string) => {
        onTopicSelect(undefined, source, category)
    }

    const handleTopicClick = (source: string, category: string, topic: string) => {
        onTopicSelect(topic, source, category)
    }

    // Helper to calculate total questions for a subject (summing all category items)
    const getSubjectStats = (subjectData: SubjectData) => {
        let total = 0
        let solved = 0
        Object.values(subjectData.categories).forEach(topics => {
            topics.forEach(t => {
                total += (t.count || 0)
                solved += (t.solved_count || 0)
            })
        })
        return { total, solved }
    }

    if (loading) {
        return (
            <div className="p-4 text-zinc-500 animate-pulse">
                Kütüphane Yükleniyor...
            </div>
        )
    }

    return (
        <div className="p-2">
            {/* All Topics Button */}
            <button
                onClick={() => onTopicSelect(undefined, undefined, undefined)}
                className={cn(
                    "w-full flex items-center gap-2 px-4 py-3 mb-2 rounded-xl text-sm font-medium transition-all",
                    !selectedTopic && !selectedSource && !selectedCategory
                        ? "bg-gradient-to-r from-red-500 to-pink-500 text-white shadow-lg"
                        : "bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-200 dark:hover:bg-zinc-700"
                )}
            >
                🎯 Tüm Konular
            </button>

            {showAdminLatest && onAdminLatestSelect && (
                <button
                    onClick={() => onAdminLatestSelect()}
                    className={cn(
                        "w-full flex items-center gap-2 px-4 py-3 mb-3 rounded-xl text-sm font-medium transition-all",
                        isLatestActive
                            ? "bg-amber-500 text-white shadow-lg"
                            : "bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-300 hover:bg-amber-100 dark:hover:bg-amber-900/30"
                    )}
                >
                    ⏱ Son Soruları Çöz (Admin)
                </button>
            )}

            {Object.entries(library).sort(([a], [b]) => a.localeCompare(b)).map(([sourceName, subjectData]) => {
                const isExpanded = expandedSubjects.has(sourceName)
                const totalStats = getSubjectStats(subjectData)
                const categories = Object.entries(subjectData.categories).sort(([a], [b]) => {
                    // Flashcards always at top? Or alphabetical? Let's do alphabetical but Flashcards first if we want.
                    if (a === "Flashcards") return -1
                    if (b === "Flashcards") return 1
                    return a.localeCompare(b)
                })

                return (
                    <div key={sourceName} className="mb-1">
                        {/* Subject Header */}
                        <div
                            className={cn(
                                "w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-all group cursor-pointer",
                                "hover:bg-zinc-100 dark:hover:bg-zinc-800",
                                selectedSource === sourceName && "bg-blue-50 dark:bg-blue-900/20"
                            )}
                            onClick={() => toggleSubject(sourceName)}
                        >
                            {isExpanded ? (
                                <ChevronDown className="w-4 h-4 text-zinc-400" />
                            ) : (
                                <ChevronRight className="w-4 h-4 text-zinc-400" />
                            )}
                            <BookOpen className="w-4 h-4 text-blue-500" />
                            <span className="flex-1 text-left">{sourceName.replace(/_/g, ' ')}</span>
                            <div className="flex items-center gap-1">
                                {totalStats.solved > 0 && (
                                    <span className="text-xs px-2 py-0.5 rounded-full bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400 font-bold">
                                        {totalStats.solved}
                                    </span>
                                )}
                                <span className={cn(
                                    "text-xs px-2 py-0.5 rounded-full",
                                    totalStats.total > 0
                                        ? "bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400"
                                        : "bg-zinc-100 dark:bg-zinc-800 text-zinc-500"
                                )}>
                                    {totalStats.total}
                                </span>
                            </div>
                            <button
                                onClick={(e) => {
                                    e.stopPropagation()
                                    onTopicSelect(undefined, sourceName, undefined)
                                }}
                                className="p-1 rounded hover:bg-blue-100 dark:hover:bg-blue-900/30 touch-none"
                                title="Bu dersle başla"
                            >
                                <Play className="w-4 h-4 text-blue-500" />
                            </button>
                        </div>

                        {/* Categories List */}
                        {isExpanded && (
                            <div className="ml-4 mt-1 space-y-0.5">
                                {categories.map(([catName, topics]) => {
                                    const catKey = `${sourceName}:${catName}`
                                    const isCatExpanded = expandedCategories.has(catKey)
                                    const isSelected = selectedCategory === catName && selectedSource === sourceName

                                    // Calculate category count sum
                                    const catTotal = topics.reduce((sum, t) => sum + (t.count || 0), 0)
                                    const catSolved = topics.reduce((sum, t) => sum + (t.solved_count || 0), 0)

                                    // Determine if this category has sub-topics to show
                                    // Logic: If topics list has >1 item OR (1 item but title != categoryName)
                                    // However, library.py logic collapses subtopics into single item if "is_category" is true.
                                    // If "is_category" is true, it means backend decided to collapse it.
                                    const isCollapsed = topics.length === 1 && topics[0].is_category
                                    const hasSubtopics = !isCollapsed && topics.length > 0

                                    if (isCollapsed) {
                                        // Render as single leaf node (Category acts as Topic)
                                        return (
                                            <div key={catKey} className="flex items-center gap-1">
                                                <div className="w-4" /> {/* Indent spacer */}
                                                <div
                                                    onClick={() => handleCategoryClick(sourceName, catName)}
                                                    className={cn(
                                                        "flex-1 flex items-center gap-2 px-2 py-1.5 rounded-lg text-sm transition-all text-left cursor-pointer",
                                                        "hover:bg-zinc-100 dark:hover:bg-zinc-800",
                                                        isSelected && "bg-purple-50 dark:bg-purple-900/20 text-purple-600 dark:text-purple-400"
                                                    )}
                                                >
                                                    <Folder className="w-4 h-4 text-amber-500" />
                                                    <span className="flex-1 truncate">{catName}</span>
                                                    <div className="flex items-center gap-1">
                                                        {catSolved > 0 && (
                                                            <span className="text-xs px-1.5 py-0.5 rounded bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400 font-semibold">
                                                                {catSolved}
                                                            </span>
                                                        )}
                                                        <span className={cn(
                                                            "text-xs px-1.5 py-0.5 rounded",
                                                            catTotal > 0
                                                                ? "bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400"
                                                                : "text-zinc-400"
                                                        )}>
                                                            {catTotal}
                                                        </span>
                                                    </div>
                                                </div>
                                                <button
                                                    onClick={() => handleCategoryClick(sourceName, catName)}
                                                    className="p-1 rounded hover:bg-purple-100 dark:hover:bg-purple-900/30"
                                                    title="Bu kategoriyle başla"
                                                >
                                                    <Play className="w-3 h-3 text-purple-500" />
                                                </button>
                                            </div>
                                        )
                                    }

                                    return (
                                        <div key={catKey}>
                                            <div className="flex items-center gap-1">
                                                {hasSubtopics ? (
                                                    <button onClick={() => toggleCategory(catKey)} className="p-0.5">
                                                        {isCatExpanded ? <ChevronDown className="w-3 h-3 text-zinc-400" /> : <ChevronRight className="w-3 h-3 text-zinc-400" />}
                                                    </button>
                                                ) : <div className="w-4" />}

                                                <div
                                                    onClick={() => handleCategoryClick(sourceName, catName)}
                                                    className={cn(
                                                        "flex-1 flex items-center gap-2 px-2 py-1.5 rounded-lg text-sm transition-all text-left cursor-pointer",
                                                        "hover:bg-zinc-100 dark:hover:bg-zinc-800",
                                                        isSelected && "bg-purple-50 dark:bg-purple-900/20 text-purple-600 dark:text-purple-400"
                                                    )}
                                                >
                                                    <Folder className="w-4 h-4 text-amber-500" />
                                                    <span className="flex-1 truncate">{catName}</span>
                                                    <span className={cn(
                                                        "text-xs px-1.5 py-0.5 rounded",
                                                        catTotal > 0
                                                            ? "bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400"
                                                            : "text-zinc-400"
                                                    )}>
                                                        {catTotal}
                                                    </span>
                                                </div>
                                                <button
                                                    onClick={() => handleCategoryClick(sourceName, catName)}
                                                    className="p-1 rounded hover:bg-purple-100 dark:hover:bg-purple-900/30"
                                                    title="Bu kategoriyle başla"
                                                >
                                                    <Play className="w-3 h-3 text-purple-500" />
                                                </button>
                                            </div>

                                            {/* Subtopics List */}
                                            {isCatExpanded && hasSubtopics && (
                                                <div className="ml-6 mt-0.5 space-y-0.5">
                                                    {topics.map((topic, idx) => {
                                                        const isTopicSelected = selectedTopic === topic.topic
                                                        return (
                                                            <button
                                                                key={`${catKey}:${idx}`}
                                                                onClick={() => handleTopicClick(sourceName, catName, topic.topic)}
                                                                className={cn(
                                                                    "w-full flex items-center gap-2 px-2 py-1 rounded text-sm transition-all text-left",
                                                                    "hover:bg-zinc-100 dark:hover:bg-zinc-800",
                                                                    isTopicSelected && "bg-green-50 dark:bg-green-900/20 text-green-600 dark:text-green-400"
                                                                )}
                                                            >
                                                                <FileText className="w-3 h-3 text-zinc-400" />
                                                                <span className="flex-1 truncate text-xs">{topic.topic}</span>
                                                                <div className="flex items-center gap-1">
                                                                    {(topic.solved_count || 0) > 0 && (
                                                                        <span className="text-xs text-green-600 dark:text-green-400 font-semibold">
                                                                            {topic.solved_count} /
                                                                        </span>
                                                                    )}
                                                                    <span className={cn(
                                                                        "text-xs",
                                                                        topic.count > 0 ? "text-green-500" : "text-zinc-400"
                                                                    )}>
                                                                        {topic.count}
                                                                    </span>
                                                                </div>
                                                            </button>
                                                        )
                                                    })}
                                                </div>
                                            )}
                                        </div>
                                    )
                                })}
                            </div>
                        )}
                    </div>
                )
            })}
        </div>
    )
}
