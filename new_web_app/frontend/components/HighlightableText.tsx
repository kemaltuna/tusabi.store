"use client"

import { useState, useCallback, useRef, useEffect } from "react"
import { cn } from "../lib/utils"
import { Highlighter } from "lucide-react"

interface HighlightableTextProps {
    text: string
    highlightedTexts: string[]
    onHighlight: (text: string) => void
    className?: string
}

export function HighlightableText({
    text,
    highlightedTexts,
    onHighlight,
    className
}: HighlightableTextProps) {
    const [isHighlightMode, setIsHighlightMode] = useState(false)
    const containerRef = useRef<HTMLDivElement>(null)

    const handleMouseUp = useCallback(() => {
        if (!isHighlightMode) return

        const selection = window.getSelection()
        if (!selection || selection.isCollapsed) return

        const selectedText = selection.toString().trim()
        if (selectedText.length < 2) return

        // Check if selection is within our container
        const container = containerRef.current
        if (!container) return

        const range = selection.getRangeAt(0)
        if (!container.contains(range.commonAncestorContainer)) return

        onHighlight(selectedText)
        selection.removeAllRanges()
    }, [isHighlightMode, onHighlight])

    // Render text with highlights applied
    const renderTextWithHighlights = () => {
        if (!text || highlightedTexts.length === 0) {
            return text
        }

        // Sort highlights by length (longest first) to avoid nested matching issues
        const sortedHighlights = [...highlightedTexts].sort((a, b) => b.length - a.length)

        let result = text
        const markers: { start: number; end: number; text: string }[] = []

        // Find all occurrences of highlighted text
        sortedHighlights.forEach(highlight => {
            let startIndex = 0
            while ((startIndex = result.indexOf(highlight, startIndex)) !== -1) {
                // Check if this range overlaps with existing markers
                const overlaps = markers.some(m =>
                    (startIndex >= m.start && startIndex < m.end) ||
                    (startIndex + highlight.length > m.start && startIndex + highlight.length <= m.end)
                )

                if (!overlaps) {
                    markers.push({
                        start: startIndex,
                        end: startIndex + highlight.length,
                        text: highlight
                    })
                }
                startIndex++
            }
        })

        // Sort markers by position
        markers.sort((a, b) => a.start - b.start)

        // Build result with highlights
        const parts: React.ReactNode[] = []
        let lastEnd = 0

        markers.forEach((marker, idx) => {
            // Add text before this highlight
            if (marker.start > lastEnd) {
                parts.push(text.slice(lastEnd, marker.start))
            }

            // Add highlighted text
            parts.push(
                <mark
                    key={idx}
                    className="bg-yellow-200 dark:bg-yellow-600/40 px-0.5 rounded cursor-pointer hover:bg-yellow-300 dark:hover:bg-yellow-500/50"
                    onClick={() => onHighlight(marker.text)}
                    title="Tıklayarak vurguyu kaldır"
                >
                    {marker.text}
                </mark>
            )

            lastEnd = marker.end
        })

        // Add remaining text
        if (lastEnd < text.length) {
            parts.push(text.slice(lastEnd))
        }

        return parts.length > 0 ? parts : text
    }

    return (
        <div className={cn("relative", className)}>
            {/* Highlight mode toggle */}
            <button
                onClick={() => setIsHighlightMode(!isHighlightMode)}
                className={cn(
                    "absolute -top-8 right-0 p-1.5 rounded transition-colors text-sm flex items-center gap-1",
                    isHighlightMode
                        ? "bg-yellow-400 text-yellow-900"
                        : "bg-zinc-200 dark:bg-zinc-700 text-zinc-600 dark:text-zinc-300 hover:bg-yellow-200"
                )}
                title={isHighlightMode ? "Vurgulama modu açık" : "Vurgulamayı etkinleştir"}
            >
                <Highlighter className="w-4 h-4" />
            </button>

            {/* Text content */}
            <div
                ref={containerRef}
                onMouseUp={handleMouseUp}
                className={cn(
                    "transition-colors",
                    isHighlightMode && "cursor-text select-text bg-yellow-50/50 dark:bg-yellow-900/10 rounded p-2 -m-2"
                )}
            >
                {renderTextWithHighlights()}
            </div>
        </div>
    )
}
