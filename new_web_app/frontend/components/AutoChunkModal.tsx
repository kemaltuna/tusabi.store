"use client"

import { useState, useEffect, useCallback } from "react"
import { X, Sparkles, Loader, Minus, Plus, ChevronDown, ChevronUp, Package, Zap } from "lucide-react"
import { cn } from "../lib/utils"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "/api"

async function parseApiError(response: Response, fallback: string): Promise<string> {
    const contentType = response.headers.get("content-type") || ""

    if (contentType.includes("application/json")) {
        try {
            const data = await response.json()
            if (typeof data?.detail === "string" && data.detail.trim()) return data.detail
            if (typeof data?.message === "string" && data.message.trim()) return data.message
        } catch {
            // fall back to plain text
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

interface SubSegmentData {
    title: string
    file: string
    page_count: number
    source_pdfs_list?: string[]
    merged_topics?: string[]
}

interface ChunkPreview {
    chunk_index: number
    topic_name: string
    topics: string[]
    page_count: number
    file_count: number
}

interface AutoChunkModalProps {
    isOpen: boolean
    onClose: () => void
    segmentTitle: string
    source: string
    subSegments: SubSegmentData[]
    totalPages: number
}

export function AutoChunkModal({
    isOpen,
    onClose,
    segmentTitle,
    source,
    subSegments,
    totalPages
}: AutoChunkModalProps) {
    const [questionCount, setQuestionCount] = useState(10)
    const [difficulty, setDifficulty] = useState(1)
    const [multiplier, setMultiplier] = useState(1)
    const [targetPages, setTargetPages] = useState(20)
    const [chunks, setChunks] = useState<ChunkPreview[]>([])
    const [loadingPreview, setLoadingPreview] = useState(false)
    const [isGenerating, setIsGenerating] = useState(false)
    const [result, setResult] = useState<string | null>(null)
    const [expandedChunks, setExpandedChunks] = useState<Set<number>>(new Set())

    const DIFFICULTY_LABELS: Record<string, string> = {
        "1": "Orta",
        "2": "Orta-Zor",
        "3": "Zor",
        "4": "Zor - Çok Zor",
    }

    const fetchPreview = useCallback(async () => {
        if (subSegments.length === 0) return
        setLoadingPreview(true)
        try {
            const token = localStorage.getItem("medquiz_token")
            const res = await fetch(`${API_BASE}/admin/preview-chunks`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    ...(token ? { Authorization: `Bearer ${token}` } : {})
                },
                body: JSON.stringify({
                    source_material: source,
                    segment_title: segmentTitle,
                    sub_segments: subSegments,
                    target_pages: targetPages
                })
            })
            if (res.ok) {
                const data = await res.json()
                setChunks(data.chunks || [])
            }
        } catch (e) {
            console.error("Preview failed:", e)
        } finally {
            setLoadingPreview(false)
        }
    }, [subSegments, source, segmentTitle, targetPages])

    useEffect(() => {
        if (isOpen) {
            fetchPreview()
            setResult(null)
        }
    }, [isOpen, fetchPreview])

    const handleGenerate = async () => {
        setIsGenerating(true)
        setResult(null)
        try {
            const token = localStorage.getItem("medquiz_token")
            const res = await fetch(`${API_BASE}/admin/auto-chunk-generate`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    ...(token ? { Authorization: `Bearer ${token}` } : {})
                },
                body: JSON.stringify({
                    source_material: source,
                    segment_title: segmentTitle,
                    sub_segments: subSegments,
                    count: questionCount,
                    difficulty: difficulty,
                    multiplier: multiplier,
                    target_pages: targetPages
                })
            })

            if (!res.ok) {
                const message = await parseApiError(res, "Generation failed")
                throw new Error(message)
            }

            const data = await res.json()
            setResult(`🚀 ${data.message}`)
        } catch (error: any) {
            setResult(`❌ Hata: ${error.message}`)
        } finally {
            setIsGenerating(false)
        }
    }

    const toggleChunkExpand = (idx: number) => {
        const newSet = new Set(expandedChunks)
        if (newSet.has(idx)) newSet.delete(idx)
        else newSet.add(idx)
        setExpandedChunks(newSet)
    }

    if (!isOpen) return null

    const totalQuestions = questionCount * multiplier * chunks.length

    return (
        <div className="fixed inset-0 z-[300] flex items-center justify-center">
            {/* Backdrop */}
            <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />

            {/* Modal */}
            <div className="relative w-full max-w-lg mx-4 max-h-[90vh] bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl border border-zinc-200 dark:border-zinc-700 flex flex-col overflow-hidden">
                {/* Header */}
                <div className="flex items-center justify-between px-6 py-4 border-b border-zinc-200 dark:border-zinc-700 bg-gradient-to-r from-purple-50 to-indigo-50 dark:from-purple-900/20 dark:to-indigo-900/20">
                    <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-purple-500 to-indigo-600 flex items-center justify-center">
                            <Zap className="w-5 h-5 text-white" />
                        </div>
                        <div>
                            <h2 className="text-lg font-bold">Otomatik Parçala & Üret</h2>
                            <p className="text-xs text-zinc-500">{segmentTitle} • {source} • {totalPages} sayfa</p>
                        </div>
                    </div>
                    <button onClick={onClose} className="p-2 hover:bg-zinc-200 dark:hover:bg-zinc-700 rounded-lg transition-colors">
                        <X className="w-5 h-5" />
                    </button>
                </div>

                {/* Content */}
                <div className="flex-1 overflow-y-auto p-6 space-y-5">
                    {/* Target Pages Slider */}
                    <div>
                        <div className="flex items-center justify-between mb-2">
                            <label className="text-sm font-medium">Hedef Sayfa Sayısı (Chunk Başı)</label>
                            <span className="text-sm font-bold text-purple-600">{targetPages} sayfa</span>
                        </div>
                        <div className="flex items-center gap-3">
                            <button onClick={() => setTargetPages(Math.max(10, targetPages - 5))}
                                className="w-8 h-8 rounded-full bg-zinc-200 dark:bg-zinc-700 flex items-center justify-center hover:bg-zinc-300">
                                <Minus className="w-4 h-4" />
                            </button>
                            <input type="range" min="10" max="40" step="5" value={targetPages}
                                onChange={(e) => setTargetPages(parseInt(e.target.value))}
                                className="flex-1 h-2 bg-zinc-200 dark:bg-zinc-700 rounded-lg appearance-none cursor-pointer accent-purple-500" />
                            <button onClick={() => setTargetPages(Math.min(40, targetPages + 5))}
                                className="w-8 h-8 rounded-full bg-zinc-200 dark:bg-zinc-700 flex items-center justify-center hover:bg-zinc-300">
                                <Plus className="w-4 h-4" />
                            </button>
                        </div>
                    </div>

                    {/* Chunk Preview */}
                    <div>
                        <div className="flex items-center justify-between mb-2">
                            <label className="text-sm font-medium">Parçalama Önizleme</label>
                            <span className="text-xs text-zinc-500">{chunks.length} chunk</span>
                        </div>
                        {loadingPreview ? (
                            <div className="flex items-center justify-center py-6 text-zinc-400">
                                <Loader className="w-5 h-5 animate-spin mr-2" />
                                Hesaplanıyor...
                            </div>
                        ) : (
                            <div className="space-y-2 max-h-48 overflow-y-auto pr-1">
                                {chunks.map((chunk) => (
                                    <div key={chunk.chunk_index}
                                        className="border border-zinc-200 dark:border-zinc-700 rounded-lg overflow-hidden">
                                        <button
                                            onClick={() => toggleChunkExpand(chunk.chunk_index)}
                                            className="w-full flex items-center justify-between px-3 py-2 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors"
                                        >
                                            <div className="flex items-center gap-2">
                                                <span className="w-6 h-6 rounded-lg bg-purple-100 dark:bg-purple-900/30 text-purple-600 text-xs font-bold flex items-center justify-center">
                                                    {chunk.chunk_index + 1}
                                                </span>
                                                <span className="text-sm font-medium truncate max-w-[200px]">
                                                    {chunk.topics.length <= 2 ? chunk.topics.join(" + ") : `${chunk.file_count} dosya`}
                                                </span>
                                            </div>
                                            <div className="flex items-center gap-2">
                                                <span className={cn(
                                                    "text-xs px-2 py-0.5 rounded-full font-medium",
                                                    Math.abs(chunk.page_count - targetPages) <= 3
                                                        ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
                                                        : "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400"
                                                )}>
                                                    {chunk.page_count}s
                                                </span>
                                                {expandedChunks.has(chunk.chunk_index)
                                                    ? <ChevronUp className="w-3 h-3 text-zinc-400" />
                                                    : <ChevronDown className="w-3 h-3 text-zinc-400" />
                                                }
                                            </div>
                                        </button>
                                        {expandedChunks.has(chunk.chunk_index) && (
                                            <div className="px-3 pb-2 pt-1 border-t border-zinc-100 dark:border-zinc-800">
                                                <ul className="space-y-0.5">
                                                    {chunk.topics.map((t, i) => (
                                                        <li key={i} className="text-xs text-zinc-500 flex items-center gap-1.5">
                                                            <span className="w-1 h-1 rounded-full bg-purple-400" />
                                                            {t}
                                                        </li>
                                                    ))}
                                                </ul>
                                            </div>
                                        )}
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>

                    {/* Question Count */}
                    <div>
                        <div className="flex items-center justify-between mb-2">
                            <label className="text-sm font-medium">Soru Sayısı (Chunk Başı)</label>
                            <div className="flex items-center gap-2">
                                <input
                                    type="number"
                                    value={questionCount}
                                    onChange={(e) => setQuestionCount(Math.max(1, Math.min(200, parseInt(e.target.value) || 1)))}
                                    className="w-16 text-center text-lg font-bold text-purple-600 bg-white dark:bg-zinc-800 border border-purple-200 dark:border-purple-700 rounded-lg px-2 py-0.5 focus:outline-none focus:ring-1 focus:ring-purple-500"
                                    min={1} max={200}
                                />
                            </div>
                        </div>
                    </div>

                    {/* Multiplier */}
                    <div>
                        <div className="flex items-center justify-between mb-2">
                            <label className="text-sm font-medium">Tekrar Sayısı (Part)</label>
                            <span className="text-sm font-medium text-purple-600">
                                {multiplier} x {questionCount} x {chunks.length} = {totalQuestions} Toplam
                            </span>
                        </div>
                        <div className="flex gap-2">
                            {[1, 2, 3, 4, 5, 6].map((m) => (
                                <button key={m} onClick={() => setMultiplier(m)}
                                    className={cn("flex-1 h-8 rounded-lg text-sm font-medium transition-all",
                                        m === multiplier ? "bg-purple-600 text-white shadow-lg shadow-purple-500/30"
                                            : "bg-zinc-200 dark:bg-zinc-700 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-300 dark:hover:bg-zinc-600"
                                    )}>x{m}</button>
                            ))}
                        </div>
                    </div>

                    {/* Difficulty */}
                    <div>
                        <div className="flex items-center justify-between mb-2">
                            <label className="text-sm font-medium">Zorluk Seviyesi</label>
                            <span className="text-sm font-medium text-purple-600">{DIFFICULTY_LABELS[String(difficulty)] || "Orta"}</span>
                        </div>
                        <div className="flex gap-2">
                            {[1, 2, 3, 4].map((level) => (
                                <button key={level} onClick={() => setDifficulty(level)}
                                    className={cn("flex-1 h-3 rounded-full transition-all",
                                        level <= difficulty ? "bg-gradient-to-r from-blue-400 via-purple-400 to-pink-500" : "bg-zinc-200 dark:bg-zinc-700",
                                        level === difficulty && "ring-2 ring-purple-500 ring-offset-2"
                                    )} />
                            ))}
                        </div>
                    </div>

                    {/* Result */}
                    {result && (
                        <div className={cn(
                            "p-3 rounded-lg text-sm text-center font-medium",
                            result.startsWith("🚀")
                                ? "bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-300"
                                : "bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300"
                        )}>
                            {result}
                        </div>
                    )}
                </div>

                {/* Footer */}
                <div className="px-6 py-4 border-t border-zinc-200 dark:border-zinc-700 flex gap-3">
                    <button onClick={onClose} disabled={isGenerating}
                        className="px-4 py-2.5 bg-zinc-200 dark:bg-zinc-700 rounded-lg text-sm font-medium hover:bg-zinc-300 disabled:opacity-50">
                        Kapat
                    </button>
                    <button onClick={handleGenerate} disabled={isGenerating || chunks.length === 0}
                        className={cn(
                            "flex-1 py-2.5 rounded-lg text-white font-bold flex items-center justify-center gap-2 transition-all",
                            isGenerating ? "bg-purple-400 cursor-wait" : "bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-700 hover:to-indigo-700",
                            chunks.length === 0 && "opacity-50 cursor-not-allowed"
                        )}>
                        {isGenerating ? (
                            <><Loader className="w-5 h-5 animate-spin" /> Gönderiliyor...</>
                        ) : (
                            <>
                                <Sparkles className="w-5 h-5" />
                                {chunks.length} Chunk × {multiplier} Part Başlat ({totalQuestions} Soru)
                            </>
                        )}
                    </button>
                </div>
            </div>
        </div>
    )
}
