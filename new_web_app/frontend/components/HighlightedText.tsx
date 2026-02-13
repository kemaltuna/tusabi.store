"use client"

import React from "react"

interface HighlightedTextProps {
    text: string
    highlights: string[]
    onHighlightClick?: (text: string) => void
    className?: string
}

/**
 * Renders text with highlights applied inline.
 * Highlights are sorted by their position in the text for consistent rendering.
 */
export function HighlightedText({
    text,
    highlights,
    onHighlightClick,
    className
}: HighlightedTextProps) {
    if (!text || highlights.length === 0) {
        return <span className={className}>{text}</span>
    }

    // Find all occurrences of highlighted text, sorted by position
    const markers: { start: number; end: number; text: string }[] = []

    // Sort highlights by length (longest first) to avoid nested matching issues
    const sortedHighlights = [...highlights].sort((a, b) => b.length - a.length)

    sortedHighlights.forEach(highlight => {
        if (!highlight) return

        let startIndex = 0
        while ((startIndex = text.indexOf(highlight, startIndex)) !== -1) {
            // Check if this range overlaps with existing markers
            const overlaps = markers.some(m =>
                (startIndex >= m.start && startIndex < m.end) ||
                (startIndex + highlight.length > m.start && startIndex + highlight.length <= m.end) ||
                (startIndex <= m.start && startIndex + highlight.length >= m.end)
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

    // Sort markers by position in text
    markers.sort((a, b) => a.start - b.start)

    // Build result with highlights
    const parts: React.ReactNode[] = []
    let lastEnd = 0

    markers.forEach((marker, idx) => {
        // Add text before this highlight
        if (marker.start > lastEnd) {
            parts.push(
                <span key={`text-${idx}`}>
                    {text.slice(lastEnd, marker.start)}
                </span>
            )
        }

        // Add highlighted text
        parts.push(
            <mark
                key={`mark-${idx}`}
                className="bg-yellow-200 dark:bg-yellow-500/40 px-0.5 rounded cursor-pointer hover:bg-yellow-300 dark:hover:bg-yellow-400/50 transition-colors"
                onClick={() => onHighlightClick?.(marker.text)}
                title="Tıklayarak vurguyu kaldır"
            >
                {marker.text}
            </mark>
        )

        lastEnd = marker.end
    })

    // Add remaining text
    if (lastEnd < text.length) {
        parts.push(
            <span key="text-end">
                {text.slice(lastEnd)}
            </span>
        )
    }

    return <span className={className}>{parts.length > 0 ? parts : text}</span>
}

/**
 * Applies highlights to HTML content (for ReactMarkdown rendered content).
 * This wraps the content and applies highlights via DOM manipulation after render.
 */
export function useHighlightRenderer(highlights: string[], onHighlightClick?: (text: string) => void) {
    // This function will be called to wrap text nodes with highlights
    const applyHighlights = (container: HTMLElement | null) => {
        if (!container || highlights.length === 0) return

        // Get all text nodes
        const walker = document.createTreeWalker(
            container,
            NodeFilter.SHOW_TEXT,
            null
        )

        const textNodes: Text[] = []
        let node: Node | null
        while ((node = walker.nextNode())) {
            textNodes.push(node as Text)
        }

        // Sort highlights by length (longest first)
        const sortedHighlights = [...highlights].sort((a, b) => b.length - a.length)

        textNodes.forEach(textNode => {
            const text = textNode.textContent || ""
            let hasHighlight = false

            for (const highlight of sortedHighlights) {
                if (text.includes(highlight)) {
                    hasHighlight = true
                    break
                }
            }

            if (!hasHighlight) return

            // Create a wrapper span with highlighted content
            const wrapper = document.createElement("span")
            let currentText = text

            sortedHighlights.forEach(highlight => {
                if (!currentText.includes(highlight)) return
                currentText = currentText.split(highlight).join(`<mark class="bg-yellow-200 dark:bg-yellow-500/40 px-0.5 rounded cursor-pointer hover:bg-yellow-300 transition-colors" data-highlight="${highlight}">${highlight}</mark>`)
            })

            wrapper.innerHTML = currentText

            // Add click handlers to marks
            wrapper.querySelectorAll("mark[data-highlight]").forEach(mark => {
                mark.addEventListener("click", () => {
                    const highlightText = mark.getAttribute("data-highlight")
                    if (highlightText) onHighlightClick?.(highlightText)
                })
            })

            textNode.parentNode?.replaceChild(wrapper, textNode)
        })
    }

    return { applyHighlights }
}
