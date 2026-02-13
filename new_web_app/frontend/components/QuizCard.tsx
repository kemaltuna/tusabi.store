"use client"

import { useState, useRef, useEffect, useCallback } from "react"
import { QuizCardData } from "../lib/types"
import { submitReview } from "../lib/api"
import ReactMarkdown from "react-markdown"
import rehypeRaw from "rehype-raw"
import rehypeKatex from "rehype-katex"
import "katex/dist/katex.min.css"
import { cn } from "../lib/utils"
import { Check, X, RefreshCw, Highlighter, Sparkles, XCircle, ChevronLeft, Flag, Plus, Minus } from "lucide-react"
import { ExplanationBlocks } from "./ExplanationBlocks"
import { useHighlights } from "../lib/useHighlights"

import { FeedbackDialog } from "./FeedbackDialog"

export function QuizCard({ card, onNext, onPrevious }: { card: QuizCardData, onNext: () => void, onPrevious?: () => void }) {
    const [selected, setSelected] = useState<number | null>(null)
    const [revealed, setRevealed] = useState(false)
    const [submitting, setSubmitting] = useState(false)
    const [highlightMode, setHighlightMode] = useState<"flashcard" | "note" | null>(null)
    const [showFlashcardHint, setShowFlashcardHint] = useState(false)
    const [feedbackOpen, setFeedbackOpen] = useState(false)
    const [fontSizeLevel, setFontSizeLevel] = useState(1) // 0: sm, 1: base, 2: lg, 3: xl
    const { highlights, toggleHighlight, removeHighlight } = useHighlights(card.id)
    const isFlashcard = !card.options || card.options.length === 0
    const isHighlightingActive = highlightMode !== null

    // Refs for applying highlights to DOM
    const questionRef = useRef<HTMLDivElement>(null)
    const explanationRef = useRef<HTMLDivElement>(null)
    const questionContextRef = useRef({ allowHighlighting: false, activeContextKey: null as string | null })
    const explanationContextRef = useRef({ allowHighlighting: false, activeContextKey: null as string | null })
    const toggleHighlightRef = useRef(toggleHighlight)
    const removeHighlightRef = useRef(removeHighlight)
    const dragState = useRef({
        active: false,
        action: "add" as "add" | "remove",
        seen: new Set<string>(),
        suppressClick: false
    })

    // Filter highlights by context type
    const questionHighlights = highlights.filter(h => h.context_type === "question")
    const flashcardHighlights = highlights.filter(h => h.context_type === "flashcard")
    const noteHighlights = highlights.filter(h => h.context_type === "explanation" || h.context_type === "note")
    const explanationHighlightCount = flashcardHighlights.length + noteHighlights.length
    const CONTEXT_WINDOW_WORDS = 6

    const formatQuestionText = (text: string) => {
        if (!text) return text
        const hasRoman = /(\bI\.|\bII\.|\bIII\.|\bIV\.)/.test(text)
        if (!hasRoman) return text
        return text
            .replace(/\s+(?=(I|II|III|IV)\.\s)/g, "<br/>")
            .replace(/\n+/g, "<br/>")
    }

    // Apply word-by-word highlighting to DOM
    const applyWordHighlights = useCallback((
        container: HTMLElement | null,
        highlightSets: { key: string; highlights: typeof highlights; className: string; title: string }[],
        activeContextKey: string | null,
        allowHighlighting: boolean
    ) => {
        if (!container) return

        // Map highlights for fast lookup
        const highlightByIndex = new Map<number, { id: number; key: string; className: string; title: string; word_index: number | null; text: string }>()
        const pendingByText = new Map<string, { id: number; key: string; className: string; title: string; word_index: number | null; text: string }[]>()

        for (const set of highlightSets) {
            for (const h of set.highlights) {
                const info = {
                    id: h.id,
                    key: set.key,
                    className: set.className,
                    title: set.title,
                    word_index: h.word_index ?? null,
                    text: h.text_content
                }
                if (h.word_index !== null && h.word_index !== undefined) {
                    highlightByIndex.set(h.word_index, info)
                } else {
                    const list = pendingByText.get(h.text_content) || []
                    list.push(info)
                    pendingByText.set(h.text_content, list)
                }
            }
        }

        // OPTIMIZATION: Check if we already have wrapped words
        const existingWrappers = container.querySelectorAll("[data-word-index]")
        if (existingWrappers.length > 0) {
            // Update existing elements in place
            // Update existing elements in place
            existingWrappers.forEach((el) => {
                if (!(el instanceof HTMLElement)) return
                const index = Number(el.dataset.wordIndex)
                if (Number.isNaN(index)) return

                const highlightInfo = highlightByIndex.get(index)
                const isHighlighted = Boolean(highlightInfo)

                // --- OPTIMIZATION: Check if update is needed ---
                const currentHighlighted = el.dataset.highlighted === "true"
                const currentContextKey = el.dataset.contextKey || ""
                const currentId = el.dataset.highlightId || ""

                const targetContextKey = isHighlighted ? (highlightInfo?.key || "") : (allowHighlighting && activeContextKey ? activeContextKey : "")
                const targetId = isHighlighted ? String(highlightInfo?.id ?? "") : ""

                // Specific Check: If highlight status, context, and ID match perfectly, SKIP DOM WRITE.
                // Note: We also check allowHighlighting vs userSelect, but userSelect rarely changes during drag unless mode changes.
                // Assuming highlightMode determines activeContextKey, which is checked above.
                if (currentHighlighted === isHighlighted &&
                    currentContextKey === targetContextKey &&
                    currentId === targetId) {
                    return // SKIP
                }
                // -----------------------------------------------

                // Update state without destroying element
                if (isHighlighted) {
                    // It is highlighted
                    el.className = `${highlightInfo?.className || ""} px-0.5 rounded cursor-pointer hover:bg-red-200 dark:hover:bg-red-500/30 transition-colors touch-none`
                    el.title = highlightInfo?.title || "Tıklayarak vurguyu kaldır"
                    el.dataset.highlighted = "true"
                    el.dataset.contextKey = highlightInfo?.key || ""
                    el.dataset.highlightId = String(highlightInfo?.id ?? "")
                    if (allowHighlighting) {
                        el.style.userSelect = "none"
                    } else {
                        el.style.userSelect = "text"
                    }
                } else if (allowHighlighting && activeContextKey) {
                    // It can be highlighted
                    el.className = `word-highlightable cursor-pointer rounded px-0.5 transition-colors touch-none ${activeContextKey === "flashcard"
                        ? "hover:bg-yellow-100 dark:hover:bg-yellow-900/30"
                        : "hover:bg-sky-100 dark:hover:bg-sky-900/30"
                        }`
                    el.title = "Tıklayarak vurgula"
                    el.dataset.highlighted = "false"
                    el.dataset.contextKey = activeContextKey
                    el.dataset.highlightId = ""
                    el.style.userSelect = "none"
                } else {
                    // Plain text mode (but keeping span to avoid layout shift)
                    el.className = "px-0.5 rounded" // Keep base padding so layout doesn't jump
                    el.title = ""
                    el.dataset.highlighted = "false"
                    el.dataset.contextKey = ""
                    el.dataset.highlightId = ""
                    el.style.userSelect = "text"
                    // Reset hover/cursor
                    el.style.cursor = "text"
                }
            })
            return
        }

        // INITIAL RENDER: Fallback to full parse if clean DOM
        // Remove existing markers/wrappers just in case we have a partial state
        container.querySelectorAll(".word-wrapper, mark, .word-highlightable").forEach(el => {
            el.replaceWith(document.createTextNode(el.textContent || ""))
        })
        container.normalize()

        // Get all text nodes
        const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, null)
        const textNodes: Text[] = []
        let node: Node | null
        while ((node = walker.nextNode())) {
            const parent = node.parentElement
            if (parent?.tagName === "MARK" || parent?.classList.contains("word-highlightable")) continue
            textNodes.push(node as Text)
        }

        let wordIndex = 0
        textNodes.forEach(textNode => {
            const text = textNode.textContent || ""
            if (!text.trim()) return

            const parts = text.split(/(\s+)/)
            if (parts.length <= 1 && !text.match(/\S/)) return

            const wrapper = document.createElement("span")
            wrapper.className = "word-wrapper"

            parts.forEach(part => {
                if (!part) return

                if (/^\s+$/.test(part)) {
                    wrapper.appendChild(document.createTextNode(part))
                    return
                }

                const currentIndex = wordIndex
                wordIndex += 1

                let highlightInfo = highlightByIndex.get(currentIndex) || null
                if (!highlightInfo) {
                    const pending = pendingByText.get(part)
                    if (pending && pending.length > 0) {
                        highlightInfo = pending.shift() || null
                    }
                }
                const isHighlighted = Boolean(highlightInfo)

                // Use SPAN for everything to ensure stable layout
                const span = document.createElement("span")
                span.dataset.wordIndex = String(currentIndex)
                span.textContent = part

                if (isHighlighted) {
                    span.className = `${highlightInfo?.className || ""} px-0.5 rounded cursor-pointer hover:bg-red-200 dark:hover:bg-red-500/30 transition-colors`
                    span.title = highlightInfo?.title || "Tıklayarak vurguyu kaldır"
                    span.dataset.highlighted = "true"
                    span.dataset.contextKey = highlightInfo?.key || ""
                    span.dataset.highlightId = String(highlightInfo?.id ?? "")
                    if (allowHighlighting) {
                        span.style.userSelect = "none"
                    }
                } else if (allowHighlighting && activeContextKey) {
                    span.className = `word-highlightable cursor-pointer rounded px-0.5 transition-colors ${activeContextKey === "flashcard"
                        ? "hover:bg-yellow-100 dark:hover:bg-yellow-900/30"
                        : "hover:bg-sky-100 dark:hover:bg-sky-900/30"
                        }`
                    span.title = "Tıklayarak vurgula"
                    span.dataset.highlighted = "false"
                    span.dataset.contextKey = activeContextKey
                    span.style.userSelect = "none"
                } else {
                    span.className = "px-0.5 rounded" // Keep padding
                }
                wrapper.appendChild(span)
            })

            if (wrapper.childNodes.length > 0) {
                textNode.parentNode?.replaceChild(wrapper, textNode)
            }
        })
    }, [])

    const buildContextSnippet = (container: HTMLElement, wordIndex: number) => {
        if (!container || Number.isNaN(wordIndex)) return null
        const start = Math.max(0, wordIndex - CONTEXT_WINDOW_WORDS)
        const end = wordIndex + CONTEXT_WINDOW_WORDS
        const words: string[] = []
        for (let i = start; i <= end; i += 1) {
            const el = container.querySelector<HTMLElement>(`[data-word-index="${i}"]`)
            const word = el?.textContent?.trim()
            if (word) {
                words.push(word)
            }
        }
        return words.length > 0 ? words.join(" ") : null
    }

    const buildTableContext = (target: HTMLElement) => {
        const cell = target.closest("td, th") as HTMLTableCellElement | null
        if (!cell) return null
        const table = cell.closest("table")
        if (!table) return null

        const cellIndex = cell.cellIndex
        let column = ""
        const headerRow = table.tHead?.rows?.[0]
        if (headerRow && headerRow.cells.length > cellIndex) {
            column = headerRow.cells[cellIndex]?.textContent?.trim() || ""
        }

        let row = ""
        const rowEl = cell.parentElement as HTMLTableRowElement | null
        if (rowEl && rowEl.parentElement?.tagName === "TBODY") {
            row = rowEl.cells[0]?.textContent?.trim() || ""
        }

        let title = ""
        const container = table.closest("div")
        const titleEl = container?.querySelector("h4")
        if (titleEl) {
            title = titleEl.textContent?.trim() || ""
        }

        const context: Record<string, string> = {}
        if (title) context.title = title
        if (row) context.row = row
        if (column) context.column = column
        return Object.keys(context).length > 0 ? context : null
    }

    const buildHighlightContext = (target: HTMLElement, container: HTMLElement) => {
        const wordIndex = Number(target.dataset.wordIndex)
        if (Number.isNaN(wordIndex)) {
            return { snippet: null, meta: null }
        }
        const snippet = buildContextSnippet(container, wordIndex)
        const tableContext = buildTableContext(target)
        const meta = tableContext ? { table: tableContext } : null
        return { snippet, meta }
    }

    useEffect(() => {
        toggleHighlightRef.current = toggleHighlight
    }, [toggleHighlight])

    useEffect(() => {
        removeHighlightRef.current = removeHighlight
    }, [removeHighlight])

    useEffect(() => {
        questionContextRef.current = {
            allowHighlighting: highlightMode === "note",
            activeContextKey: highlightMode === "note" ? "question" : null
        }
        explanationContextRef.current = {
            allowHighlighting: highlightMode !== null,
            activeContextKey: highlightMode === "flashcard" ? "flashcard" : highlightMode === "note" ? "explanation" : null
        }
    }, [highlightMode])

    useEffect(() => {
        const attachHandlers = (container: HTMLElement | null, contextRef: typeof questionContextRef) => {
            if (!container) return () => { }

            const getWordTarget = (target: EventTarget | null) => {
                if (!(target instanceof HTMLElement)) return null
                return target.closest<HTMLElement>("[data-word-index]")
            }

            const handleDragAction = (target: HTMLElement, isHighlighted: boolean, activeContainer: HTMLElement) => {
                const wordIndex = Number(target.dataset.wordIndex)
                if (Number.isNaN(wordIndex)) return
                const word = target.textContent || ""
                if (dragState.current.seen.has(String(wordIndex))) return
                dragState.current.seen.add(String(wordIndex))

                const activeContextKey = contextRef.current.activeContextKey
                if (dragState.current.action === "add" && !isHighlighted && activeContextKey) {
                    const { snippet, meta } = buildHighlightContext(target, activeContainer)
                    toggleHighlightRef.current(word, activeContextKey, wordIndex, snippet, meta)
                    return
                }

                if (dragState.current.action === "remove" && isHighlighted) {
                    const highlightId = target.dataset.highlightId
                    if (highlightId) {
                        removeHighlightRef.current(Number(highlightId))
                        return
                    }
                    const contextKey = target.dataset.contextKey || null
                    if (contextKey) {
                        const { snippet, meta } = buildHighlightContext(target, activeContainer)
                        toggleHighlightRef.current(word, contextKey, wordIndex, snippet, meta)
                    }
                }
            }

            const onPointerDown = (event: PointerEvent) => {
                const target = getWordTarget(event.target)
                if (!target) return
                const { allowHighlighting } = contextRef.current
                if (!allowHighlighting) return
                event.preventDefault()

                const isHighlighted = target.dataset.highlighted === "true"
                dragState.current.active = true
                dragState.current.action = isHighlighted ? "remove" : "add"
                dragState.current.seen.clear()
                dragState.current.suppressClick = true
                handleDragAction(target, isHighlighted, container)
            }

            const onPointerOver = (event: PointerEvent) => {
                if (!dragState.current.active) return
                const { allowHighlighting } = contextRef.current
                if (!allowHighlighting) return
                const target = getWordTarget(event.target)
                if (!target) return
                event.preventDefault()
                const isHighlighted = target.dataset.highlighted === "true"
                handleDragAction(target, isHighlighted, container)
            }

            const onClick = (event: MouseEvent) => {
                const target = getWordTarget(event.target)
                if (!target) return
                if (dragState.current.suppressClick) return
                if (target.dataset.highlighted !== "true") return
                const highlightId = target.dataset.highlightId
                if (highlightId) {
                    removeHighlightRef.current(Number(highlightId))
                } else {
                    const wordIndex = Number(target.dataset.wordIndex)
                    const contextKey = target.dataset.contextKey || null
                    if (!Number.isNaN(wordIndex) && contextKey) {
                        const word = target.textContent || ""
                        const { snippet, meta } = buildHighlightContext(target, container)
                        toggleHighlightRef.current(word, contextKey, wordIndex, snippet, meta)
                    }
                }
            }

            const onTouchMove = (event: TouchEvent) => {
                if (!dragState.current.active) return
                const { allowHighlighting } = contextRef.current
                if (!allowHighlighting) return

                // Prevent scrolling while dragging to highlight
                if (event.cancelable) event.preventDefault()

                const touch = event.touches[0]
                const target = document.elementFromPoint(touch.clientX, touch.clientY)
                const wordTarget = getWordTarget(target)

                if (wordTarget) {
                    const isHighlighted = wordTarget.dataset.highlighted === "true"
                    handleDragAction(wordTarget, isHighlighted, container)
                }
            }

            container.addEventListener("pointerdown", onPointerDown)
            container.addEventListener("pointerover", onPointerOver)
            container.addEventListener("touchmove", onTouchMove, { passive: false })
            container.addEventListener("click", onClick)

            return () => {
                container.removeEventListener("pointerdown", onPointerDown)
                container.removeEventListener("pointerover", onPointerOver)
                container.removeEventListener("touchmove", onTouchMove)
                container.removeEventListener("click", onClick)
            }
        }

        const cleanupQuestion = attachHandlers(questionRef.current, questionContextRef)
        const cleanupExplanation = attachHandlers(explanationRef.current, explanationContextRef)

        return () => {
            cleanupQuestion()
            cleanupExplanation()
        }
    }, [revealed])

    useEffect(() => {
        const endDrag = () => {
            if (!dragState.current.active && !dragState.current.suppressClick) return
            dragState.current.active = false
            dragState.current.seen.clear()
            if (dragState.current.suppressClick) {
                setTimeout(() => {
                    dragState.current.suppressClick = false
                }, 0)
            }
        }
        window.addEventListener("pointerup", endDrag)
        window.addEventListener("pointercancel", endDrag)
        window.addEventListener("mouseup", endDrag)
        window.addEventListener("touchend", endDrag)
        return () => {
            window.removeEventListener("pointerup", endDrag)
            window.removeEventListener("pointercancel", endDrag)
            window.removeEventListener("mouseup", endDrag)
            window.removeEventListener("touchend", endDrag)
        }
    }, [])

    // Apply highlights when they change or mode changes
    useEffect(() => {
        const timer = setTimeout(() => {
            applyWordHighlights(
                questionRef.current,
                [
                    {
                        key: "question",
                        highlights: questionHighlights,
                        className: "bg-sky-200 dark:bg-sky-500/40",
                        title: "Tıklayarak vurguyu kaldır"
                    }
                ],
                highlightMode === "note" ? "question" : null,
                highlightMode === "note"
            )
        }, 50)
        return () => clearTimeout(timer)
    }, [questionHighlights, highlightMode, applyWordHighlights])

    // Apply explanation highlights
    useEffect(() => {
        if (revealed && explanationRef.current) {
            const timer = setTimeout(() => {
                applyWordHighlights(
                    explanationRef.current,
                    [
                        {
                            key: "flashcard",
                            highlights: flashcardHighlights,
                            className: "bg-yellow-200 dark:bg-yellow-500/40",
                            title: "Flashcard vurgusu - kaldırmak için tıkla"
                        },
                        {
                            key: "explanation",
                            highlights: noteHighlights,
                            className: "bg-sky-200 dark:bg-sky-500/40",
                            title: "Not vurgusu - kaldırmak için tıkla"
                        }
                    ],
                    highlightMode === "flashcard" ? "flashcard" : highlightMode === "note" ? "explanation" : null,
                    highlightMode !== null
                )
            }, 100)
            return () => clearTimeout(timer)
        }
    }, [revealed, flashcardHighlights, noteHighlights, highlightMode, applyWordHighlights])

    const handleSelect = (idx: number) => {
        if (revealed) return
        setSelected(idx)
    }

    const handleReveal = () => {
        if (!isFlashcard && selected === null) return
        setRevealed(true)
    }

    const handleGrade = async (grade: string) => {
        setSubmitting(true)
        try {
            await submitReview(card.id, grade)
            onNext()
            // Reset state
            setSelected(null)
            setRevealed(false)
        } finally {
            setSubmitting(false)
        }
    }

    useEffect(() => {
        if (!showFlashcardHint) return
        const timer = setTimeout(() => setShowFlashcardHint(false), 3000)
        return () => clearTimeout(timer)
    }, [showFlashcardHint])

    const handleFontSizeChange = (delta: number) => {
        setFontSizeLevel(prev => Math.min(Math.max(0, prev + delta), 3))
    }

    const getFontSizeName = () => {
        const sizes = ["sm", "base", "lg", "xl"] as const
        return sizes[fontSizeLevel]
    }

    const isCorrect = selected === card.correct_answer_index

    return (
        <>
            {/* Font Size Controls - Fixed Top Left */}
            <div className="fixed top-20 left-2 z-40 flex flex-col gap-1 bg-white/80 dark:bg-zinc-900/80 p-1.5 rounded-lg border border-zinc-200 dark:border-zinc-800 shadow-sm opacity-50 hover:opacity-100 transition-opacity backdrop-blur">
                <button
                    onClick={() => handleFontSizeChange(1)}
                    className="p-1.5 hover:bg-zinc-100 dark:hover:bg-zinc-800 rounded transition-colors"
                    title="Yazı Boyutunu Büyüt"
                >
                    <Plus className="w-4 h-4" />
                </button>
                <div className="h-px bg-zinc-200 dark:bg-zinc-700 mx-1" />
                <button
                    onClick={() => handleFontSizeChange(-1)}
                    className="p-1.5 hover:bg-zinc-100 dark:hover:bg-zinc-800 rounded transition-colors"
                    title="Yazı Boyutunu Küçült"
                >
                    <Minus className="w-4 h-4" />
                </button>
            </div>

            <div className={cn(
                "w-full max-w-3xl mx-auto p-2 sm:p-4 bg-white dark:bg-zinc-900 rounded-xl shadow-sm border border-zinc-100 dark:border-zinc-800/50",
                revealed && "pb-24"
            )}>
                {/* Header */}
                <div className="flex justify-between items-center mb-4 text-sm text-zinc-500">
                    <div className="flex items-center gap-2">
                        {onPrevious && (
                            <button
                                onClick={onPrevious}
                                className="p-1 hover:bg-zinc-100 dark:hover:bg-zinc-800 rounded-full transition-colors mr-1"
                                title="Önceki Soru"
                            >
                                <ChevronLeft className="w-5 h-5" />
                            </button>
                        )}
                        <span>{card.source_material}</span>
                    </div>
                    <div className="flex items-center gap-2">
                        <span>{card.category}</span>
                        <button
                            onClick={() => handleGrade('block')}
                            disabled={submitting}
                            className="text-zinc-400 hover:text-red-500 transition-colors p-1 ml-2"
                            title="Bir daha gösterme"
                        >
                            <XCircle className="w-5 h-5" />
                        </button>
                        <button
                            onClick={() => setFeedbackOpen(true)}
                            className="text-zinc-400 hover:text-amber-500 transition-colors p-1"
                            title="Hata Bildir / Feedback"
                        >
                            <Flag className="w-5 h-5" />
                        </button>
                    </div>
                </div>

                <FeedbackDialog
                    isOpen={feedbackOpen}
                    onClose={() => setFeedbackOpen(false)}
                    questionId={card.id}
                />

                {/* Question - Word-by-word highlightable */}
                <div
                    key={card.id}
                    ref={questionRef}
                    className={cn(
                        "prose dark:prose-invert max-w-none mb-6 break-words px-2",
                        isHighlightingActive && "bg-yellow-50/50 dark:bg-yellow-900/10 rounded p-2 -m-2",
                        // Dynamic Font Size for Question
                        fontSizeLevel === 0 ? "prose-sm" :
                            fontSizeLevel === 1 ? "prose-base" :
                                fontSizeLevel === 2 ? "prose-lg" : "prose-xl"
                    )}
                >
                    <ReactMarkdown rehypePlugins={[rehypeRaw, rehypeKatex]}>
                        {formatQuestionText(card.question_text)}
                    </ReactMarkdown>
                </div>

                {/* Question Highlights Count */}
                {questionHighlights.length > 0 && !isHighlightingActive && (
                    <div className="mb-4 text-xs text-zinc-500">
                        📌 {questionHighlights.length} soru vurgusu
                    </div>
                )}

                {/* Options */}
                {!isFlashcard && (
                    <div className="space-y-3 mb-6">
                        {card.options.map((opt, idx) => {
                            // Handle both string and object option formats
                            const optionText = typeof opt === 'string' ? opt : (opt?.text || opt?.id || String(opt))
                            let stateStyles = "hover:bg-zinc-100 dark:hover:bg-zinc-800"

                            if (revealed) {
                                if (idx === card.correct_answer_index) {
                                    stateStyles = "bg-green-100 dark:bg-green-900/30 border-green-500 text-green-700 font-medium"
                                } else if (idx === selected) {
                                    stateStyles = "bg-red-100 dark:bg-red-900/30 border-red-500 text-red-700"
                                } else {
                                    stateStyles = "opacity-50"
                                }
                            } else if (selected === idx) {
                                stateStyles = "bg-blue-50 dark:bg-blue-900/30 border-blue-500"
                            }

                            // Font size for options
                            const optionSize = fontSizeLevel === 0 ? "text-sm" :
                                fontSizeLevel === 1 ? "text-base" :
                                    fontSizeLevel === 2 ? "text-lg" : "text-xl"

                            return (
                                <button
                                    key={idx}
                                    onClick={() => handleSelect(idx)}
                                    className={cn(
                                        "w-full text-left p-4 rounded-lg border border-zinc-200 dark:border-zinc-700 transition-all shadow-sm",
                                        optionSize,
                                        stateStyles
                                    )}
                                >
                                    {optionText}
                                </button>
                            )
                        })}
                    </div>
                )}

                {/* Controls */}
                <div className="flex flex-col gap-4">
                    {!revealed ? (
                        <button
                            onClick={handleReveal}
                            disabled={!isFlashcard && selected === null}
                            className="w-full py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-semibold disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            Cevabı Göster
                        </button>
                    ) : (
                        <div className="animation-fade-in space-y-4">
                            {/* Explanation */}
                            {card.explanation_data && (
                                <div className={cn(
                                    "pt-6 border-t border-zinc-200 dark:border-zinc-700 mt-6 relative", // Removed box style, added separator
                                    isHighlightingActive && "bg-yellow-50/30 dark:bg-yellow-900/10 rounded-lg p-2"
                                )}>
                                    <h4 className={cn("font-bold mb-3",
                                        fontSizeLevel === 0 ? "text-base" :
                                            fontSizeLevel === 1 ? "text-lg" :
                                                fontSizeLevel === 2 ? "text-xl" : "text-2xl"
                                    )}>Açıklama</h4>
                                    <div ref={explanationRef} key={`${card.id}-explanation`}>
                                        <ExplanationBlocks data={card.explanation_data} fontSize={getFontSizeName()} />
                                    </div>

                                    {/* Explanation Highlights Count */}
                                    {explanationHighlightCount > 0 && !isHighlightingActive && (
                                        <div className="mt-3 text-xs text-zinc-500">
                                            📌 {flashcardHighlights.length} flashcard, {noteHighlights.length} not vurgusu
                                        </div>
                                    )}
                                </div>
                            )}

                        </div>
                    )}
                </div>

                {revealed && (
                    <div className="fixed bottom-0 left-0 w-full z-40 bg-white/90 dark:bg-zinc-900/90 border-t border-zinc-200 dark:border-zinc-800 backdrop-blur">
                        <div className="max-w-3xl mx-auto px-4 py-3">
                            <div className="grid grid-cols-4 gap-2">
                                <GradeButton grade="again" label="Tekrar" interval="1-2 gün" color="bg-red-500" onClick={handleGrade} disabled={submitting} />
                                <GradeButton grade="hard" label="Zor" interval="4-8 gün" color="bg-orange-500" onClick={handleGrade} disabled={submitting} />
                                <GradeButton grade="good" label="İyi" interval="3-5 hafta" color="bg-blue-500" onClick={handleGrade} disabled={submitting} />
                                <GradeButton grade="easy" label="Kolay" interval="3-4 ay" color="bg-green-500" onClick={handleGrade} disabled={submitting} />
                            </div>
                        </div>
                    </div>
                )}

                <div className="fixed bottom-24 right-6 z-50 flex flex-col items-end gap-2">
                    {showFlashcardHint && (
                        <div className="max-w-xs text-xs text-zinc-700 dark:text-zinc-200 bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg px-3 py-2 shadow-lg animate-fade-in">
                            <p className="font-medium mb-1">💡 İpucu: Sıralama Önemli!</p>
                            <p>Tablo veya liste içeriğinde highlight yaparken <strong>anlamlı bir sıra</strong> ile işaretleyin. AI, kelimelerinizi dizindeki sıraya göre değil, <strong>işaretlediğiniz sıraya</strong> göre işleyecek. Bu sayede bağlam korunur.</p>
                        </div>
                    )}
                    <button
                        onClick={() => {
                            const next = highlightMode === "flashcard" ? null : "flashcard"
                            setHighlightMode(next)
                            if (next === "flashcard") {
                                setShowFlashcardHint(true)
                            } else {
                                setShowFlashcardHint(false)
                            }
                        }}
                        className={cn(
                            "flex items-center gap-2 px-3 py-2 rounded-full text-xs font-medium shadow-lg border transition-colors",
                            highlightMode === "flashcard"
                                ? "bg-yellow-400 text-yellow-900 border-yellow-300"
                                : "bg-white dark:bg-zinc-900 text-zinc-600 dark:text-zinc-300 border-zinc-200 dark:border-zinc-700 hover:bg-yellow-50"
                        )}
                        title="Flashcard üreten highlighter"
                    >
                        <Sparkles className="w-4 h-4" />
                        Flashcard Highlighter
                    </button>
                    <button
                        onClick={() => {
                            const next = highlightMode === "note" ? null : "note"
                            setHighlightMode(next)
                            setShowFlashcardHint(false)
                        }}
                        className={cn(
                            "flex items-center gap-2 px-3 py-2 rounded-full text-xs font-medium shadow-lg border transition-colors",
                            highlightMode === "note"
                                ? "bg-sky-400 text-sky-900 border-sky-300"
                                : "bg-white dark:bg-zinc-900 text-zinc-600 dark:text-zinc-300 border-zinc-200 dark:border-zinc-700 hover:bg-sky-50"
                        )}
                        title="Flashcard üretmeyen highlighter"
                    >
                        <Highlighter className="w-4 h-4" />
                        Not Highlighter
                    </button>
                </div>
            </div>
        </>
    )
}

function GradeButton({ grade, label, interval, color, onClick, disabled }: any) {
    return (
        <button
            onClick={() => onClick(grade)}
            disabled={disabled}
            className={cn("py-3 rounded-lg text-white font-bold transition-transform active:scale-95 flex flex-col items-center justify-center gap-0.5", color)}
        >
            <span>{label}</span>
            {interval && <span className="text-[10px] opacity-90 font-medium">{interval}</span>}
        </button>
    )
}
