"use client"

import { useState, useEffect, useCallback } from "react"
import { useAuth } from "./auth"

export interface Highlight {
    id: number
    user_id: number
    question_id: number
    text_content: string
    context_type: string
    word_index: number | null
    created_at: string
    context_snippet?: string | null
    context_meta?: Record<string, unknown> | null
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "/api"

export function useHighlights(questionId: number | undefined) {
    const [highlights, setHighlights] = useState<Highlight[]>([])
    const [isLoading, setIsLoading] = useState(false)
    const { token } = useAuth()

    // Fetch highlights for this question
    const fetchHighlights = useCallback(async () => {
        if (!questionId || !token) return

        setIsLoading(true)
        try {
            const res = await fetch(`${API_BASE}/highlights/${questionId}`, {
                headers: { Authorization: `Bearer ${token}` }
            })
            if (res.ok) {
                const data = await res.json()
                setHighlights(data)
            }
        } catch (err) {
            console.error("Failed to fetch highlights:", err)
        } finally {
            setIsLoading(false)
        }
    }, [questionId, token])

    useEffect(() => {
        fetchHighlights()
    }, [fetchHighlights])

    // Check if a text is highlighted
    const findHighlight = (
        text: string,
        contextType: string = "explanation",
        wordIndex?: number | null
    ): Highlight | undefined => {
        if (wordIndex !== undefined && wordIndex !== null) {
            return highlights.find(h => h.word_index === wordIndex && h.context_type === contextType)
        }
        return highlights.find(h => h.text_content === text && h.context_type === contextType)
    }

    // Toggle highlight for selected text
    const toggleHighlight = async (
        text: string,
        contextType: string = "explanation",
        wordIndex?: number | null,
        contextSnippet?: string | null,
        contextMeta?: Record<string, unknown> | null
    ) => {
        const existing = findHighlight(text, contextType, wordIndex)
        if (existing) {
            return await removeHighlight(existing.id)
        } else {
            return await addHighlight(text, contextType, wordIndex, contextSnippet, contextMeta)
        }
    }

    // Optimistic Add
    const addHighlight = async (
        textContent: string,
        contextType: string = "explanation",
        wordIndex?: number | null,
        contextSnippet?: string | null,
        contextMeta?: Record<string, unknown> | null
    ) => {
        if (!questionId || !token) return null

        // 1. Optimistic Update
        const tempId = -Date.now()
        const tempHighlight: Highlight = {
            id: tempId,
            user_id: 0,
            question_id: questionId,
            text_content: textContent,
            context_type: contextType,
            word_index: wordIndex ?? null,
            created_at: new Date().toISOString(),
            context_snippet: contextSnippet ?? null,
            context_meta: contextMeta ?? null
        }
        setHighlights(prev => [...prev, tempHighlight])

        try {
            const res = await fetch(`${API_BASE}/highlights`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    Authorization: `Bearer ${token}`
                },
                body: JSON.stringify({
                    question_id: questionId,
                    text_content: textContent,
                    context_type: contextType,
                    word_index: wordIndex ?? null,
                    context_snippet: contextSnippet ?? null,
                    context_meta: contextMeta ?? null
                })
            })

            if (res.ok) {
                const newHighlight = await res.json()
                // Replace temp with real
                setHighlights(prev => prev.map(h => h.id === tempId ? newHighlight : h))
                return newHighlight
            } else {
                // Revert on failure
                setHighlights(prev => prev.filter(h => h.id !== tempId))
            }
        } catch (err) {
            console.error("Failed to add highlight:", err)
            // Revert
            setHighlights(prev => prev.filter(h => h.id !== tempId))
        }
        return null
    }

    // Optimistic Remove
    const removeHighlight = async (highlightId: number) => {
        if (!token) return false

        // 1. Optimistic Update (Find and Remove)
        const toRemove = highlights.find(h => h.id === highlightId)
        if (!toRemove) return false

        setHighlights(prev => prev.filter(h => h.id !== highlightId))

        // If it's a temp highlight, don't sync to API (it doesn't exist there yet)
        if (highlightId < 0) {
            return true
        }

        try {
            const res = await fetch(`${API_BASE}/highlights/${highlightId}`, {
                method: "DELETE",
                headers: { Authorization: `Bearer ${token}` }
            })

            if (res.ok) {
                return true
            } else {
                // Revert
                setHighlights(prev => [...prev, toRemove])
            }
        } catch (err) {
            console.error("Failed to delete highlight:", err)
            // Revert
            setHighlights(prev => [...prev, toRemove])
        }
        return false
    }

    return {
        highlights,
        isLoading,
        addHighlight,
        removeHighlight,
        findHighlight,
        toggleHighlight,
        refetch: fetchHighlights
    }
}
