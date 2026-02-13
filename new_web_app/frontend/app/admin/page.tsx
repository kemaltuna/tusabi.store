"use client"

import { useState, useEffect, useMemo } from "react"
import { useRouter } from "next/navigation"
import { useAuth } from "../../lib/auth"
import { Settings, RefreshCw, Check, LogOut } from "lucide-react"
import { cn } from "../../lib/utils"

interface RecentQuestion {
    id: number
    source_material: string | null
    category: string | null
    topic: string | null
    question_text: string
    options?: Array<string | { id?: string; text?: string }>
    correct_answer_index?: number | null
    explanation_data?: any
    tags?: string[] | null
    created_at: string
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "/api"

export default function AdminPage() {
    const { user, isLoading: authLoading, logout } = useAuth()
    const router = useRouter()

    // Auth check
    useEffect(() => {
        if (!authLoading) {
            if (!user) {
                router.push("/login")
            } else if (user.role !== "admin") {
                router.push("/dashboard")
            }
        }
    }, [authLoading, user, router])


    if (authLoading || !user) {
        return (
            <div className="min-h-screen bg-zinc-50 dark:bg-black flex items-center justify-center">
                <RefreshCw className="w-8 h-8 animate-spin text-blue-500" />
            </div>
        )
    }

    if (user.role !== "admin") {
        return null
    }

    return (
        <div className="min-h-screen bg-zinc-50 dark:bg-black text-zinc-900 dark:text-zinc-100">
            {/* Header */}
            <header className="bg-white dark:bg-zinc-900 border-b border-zinc-200 dark:border-zinc-800 p-4 flex justify-between items-center">
                <div className="flex items-center gap-3">
                    <Settings className="w-6 h-6 text-purple-500" />
                    <h1 className="text-xl font-bold">Admin Panel</h1>
                </div>
                <div className="flex items-center gap-4">
                    <button
                        onClick={() => router.push("/dashboard")}
                        className="text-sm text-zinc-500 hover:text-zinc-700"
                    >
                        ← Dashboard
                    </button>
                    <button onClick={() => { logout(); router.push("/login") }} className="text-zinc-500 hover:text-red-500">
                        <LogOut className="w-5 h-5" />
                    </button>
                </div>
            </header>

            <main className="max-w-4xl mx-auto p-6">
                <RecentQuestionsSection />

                {/* Feedback Management Section */}
                <FeedbackSection />
            </main>
        </div>
    )
}

function FeedbackSection() {
    const { token } = useAuth()
    const [feedbacks, setFeedbacks] = useState<any[]>([])
    const [loading, setLoading] = useState(false)
    const [filter, setFilter] = useState('pending')
    const [resolving, setResolving] = useState<number | null>(null)

    useEffect(() => {
        if (token) fetchFeedbacks()
    }, [token, filter])

    const fetchFeedbacks = async () => {
        setLoading(true)
        try {
            const res = await fetch(`${API_BASE}/admin/feedbacks?status=${filter}`, {
                headers: { Authorization: `Bearer ${token}` }
            })
            if (res.ok) {
                const data = await res.json()
                setFeedbacks(data)
            }
        } catch (err) {
            console.error(err)
        } finally {
            setLoading(false)
        }
    }

    const handleResolve = async (id: number, status: string) => {
        setResolving(id)
        try {
            const res = await fetch(`${API_BASE}/admin/feedbacks/${id}/resolve`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    Authorization: `Bearer ${token}`
                },
                body: JSON.stringify({ status })
            })
            if (res.ok) {
                // Remove from list if filter is pending, else update locally
                if (filter === 'pending') {
                    setFeedbacks(prev => prev.filter(f => f.id !== id))
                } else {
                    setFeedbacks(prev => prev.map(f => f.id === id ? { ...f, status } : f))
                }
            }
        } catch (err) {
            console.error(err)
        } finally {
            setResolving(null)
        }
    }

    return (
        <section className="bg-white dark:bg-zinc-900 rounded-lg p-6 mb-6">
            <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-bold">Geri Bildirimler / Feedback</h2>
                <div className="flex gap-2">
                    <select
                        value={filter}
                        onChange={(e) => setFilter(e.target.value)}
                        className="text-sm border rounded p-1 dark:bg-zinc-800 dark:border-zinc-700"
                    >
                        <option value="pending">Bekleyenler</option>
                        <option value="resolved">Çözülenler</option>
                        <option value="ignored">Yok Sayılanlar</option>
                        <option value="all">Tümü</option>
                    </select>
                    <button onClick={fetchFeedbacks} className="text-zinc-500 hover:text-zinc-700">
                        <RefreshCw className={cn("w-4 h-4", loading && "animate-spin")} />
                    </button>
                </div>
            </div>

            {feedbacks.length === 0 ? (
                <p className="text-zinc-500 text-sm italic">Bu kategoride geri bildirim yok.</p>
            ) : (
                <div className="space-y-3">
                    {feedbacks.map(f => (
                        <div key={f.id} className="border border-zinc-200 dark:border-zinc-800 rounded p-3 text-sm">
                            <div className="flex justify-between items-start mb-2">
                                <span className={cn(
                                    "px-2 py-0.5 rounded text-xs font-medium uppercase",
                                    f.feedback_type === 'wrong_answer' ? "bg-red-100 text-red-700" :
                                        f.feedback_type === 'typo' ? "bg-yellow-100 text-yellow-700" :
                                            "bg-blue-100 text-blue-700"
                                )}>
                                    {f.feedback_type}
                                </span>
                                <span className="text-xs text-zinc-400">
                                    {new Date(f.created_at).toLocaleDateString()}
                                </span>
                            </div>

                            <p className="font-medium text-zinc-900 dark:text-zinc-100 mb-1">
                                {f.question_text ? f.question_text.substring(0, 100) + "..." : "Soru metni bulunamadı"}
                            </p>

                            {f.description && (
                                <p className="text-zinc-600 dark:text-zinc-400 italic mb-3 bg-zinc-50 dark:bg-zinc-800/50 p-2 rounded">
                                    "{f.description}"
                                </p>
                            )}

                            <div className="flex items-center justify-between mt-2 pt-2 border-t border-zinc-100 dark:border-zinc-800">
                                <span className="text-xs text-zinc-400">User ID: {f.user_id} • Question ID: {f.question_id}</span>

                                {f.status === 'pending' && (
                                    <div className="flex gap-2">
                                        <button
                                            onClick={() => handleResolve(f.id, 'ignored')}
                                            disabled={resolving === f.id}
                                            className="px-2 py-1 text-xs text-zinc-500 hover:bg-zinc-100 rounded"
                                        >
                                            Yoksay
                                        </button>
                                        <button
                                            onClick={() => handleResolve(f.id, 'resolved')}
                                            disabled={resolving === f.id}
                                            className="px-2 py-1 text-xs bg-green-600 text-white rounded hover:bg-green-700 flex items-center gap-1"
                                        >
                                            {resolving === f.id ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
                                            Çözüldü İşaretle
                                        </button>
                                    </div>
                                )}
                                {f.status !== 'pending' && (
                                    <span className={cn(
                                        "text-xs font-bold",
                                        f.status === 'resolved' ? "text-green-600" : "text-zinc-500"
                                    )}>
                                        {f.status === 'resolved' ? 'ÇÖZÜLDÜ' : 'YOK SAYILDI'}
                                    </span>
                                )}
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </section>
    )
}

function RecentQuestionsSection() {
    const { token } = useAuth()
    const [recentQuestions, setRecentQuestions] = useState<RecentQuestion[]>([])
    const [recentLimit, setRecentLimit] = useState(50)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({})
    const [openQuestions, setOpenQuestions] = useState<Record<number, boolean>>({})

    const fetchRecentQuestions = async (limitOverride?: number) => {
        if (!token) return
        const effectiveLimit = limitOverride ?? recentLimit
        setLoading(true)
        setError(null)
        try {
            const res = await fetch(`${API_BASE}/admin/recent-questions?limit=${effectiveLimit}`, {
                headers: { Authorization: `Bearer ${token}` }
            })
            if (res.ok) {
                const data = await res.json()
                setRecentQuestions(data)
            } else {
                setError("Son sorular alınamadı")
            }
        } catch (err) {
            console.error(err)
            setError("Son sorular alınamadı")
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => {
        if (token) fetchRecentQuestions()
    }, [token])

    const grouped = useMemo(() => {
        const result: Record<string, Record<string, RecentQuestion[]>> = {}
        for (const item of recentQuestions) {
            const source = item.source_material?.trim() || "Bilinmeyen Kaynak"
            const category = item.category?.trim() || item.topic?.trim() || "Kategorisiz"
            if (!result[source]) {
                result[source] = {}
            }
            if (!result[source][category]) {
                result[source][category] = []
            }
            result[source][category].push(item)
        }
        return result
    }, [recentQuestions])

    const toggleGroup = (key: string) => {
        setOpenGroups(prev => ({ ...prev, [key]: !prev[key] }))
    }

    const toggleQuestion = (id: number) => {
        setOpenQuestions(prev => ({ ...prev, [id]: !prev[id] }))
    }

    const formatDate = (value: string) => {
        const date = new Date(value)
        if (Number.isNaN(date.getTime())) return value
        return date.toLocaleString("tr-TR", {
            day: "2-digit",
            month: "2-digit",
            hour: "2-digit",
            minute: "2-digit"
        })
    }

    const truncate = (text: string, max = 180) => {
        if (text.length <= max) return text
        return `${text.slice(0, max)}...`
    }

    const renderOptionText = (opt: string | { id?: string; text?: string }) => {
        if (typeof opt === "string") return opt
        return opt?.text || opt?.id || ""
    }

    const renderOptionLabel = (opt: string | { id?: string; text?: string }, idx: number) => {
        if (typeof opt === "string") return String.fromCharCode(65 + idx)
        return opt?.id || String.fromCharCode(65 + idx)
    }

    const renderExplanation = (data: any) => {
        if (!data) return null
        if (typeof data === "string") {
            return (
                <div className="text-sm text-zinc-700 dark:text-zinc-300 whitespace-pre-wrap">
                    {data}
                </div>
            )
        }
        const main = data.main_mechanism || data.explanation || data.text
        const clinical = data.clinical_significance
        const blocks = Array.isArray(data.blocks) ? data.blocks.length : 0
        const hasContent = Boolean(main || clinical || blocks > 0)
        if (!hasContent) return null
        return (
            <div className="space-y-2 text-sm text-zinc-700 dark:text-zinc-300">
                {main && (
                    <div className="whitespace-pre-wrap">
                        {main}
                    </div>
                )}
                {clinical && (
                    <div className="whitespace-pre-wrap text-zinc-600 dark:text-zinc-400">
                        {clinical}
                    </div>
                )}
                {blocks > 0 && (
                    <div className="text-xs text-zinc-500">
                        Detay blokları: {blocks}
                    </div>
                )}
            </div>
        )
    }

    return (
        <section className="bg-white dark:bg-zinc-900 rounded-lg p-6 mb-6">
            <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-bold">Son Üretilen Sorular (Kategorili)</h2>
                <div className="flex items-center gap-2">
                    <input
                        type="number"
                        min={1}
                        max={200}
                        value={recentLimit}
                        onChange={(e) => {
                            const next = parseInt(e.target.value, 10)
                            if (Number.isNaN(next)) {
                                setRecentLimit(50)
                            } else {
                                setRecentLimit(Math.min(200, Math.max(1, next)))
                            }
                        }}
                        className="w-20 p-1 border rounded text-sm dark:bg-zinc-800 dark:border-zinc-700"
                    />
                    <button
                        onClick={() => fetchRecentQuestions()}
                        className="text-zinc-500 hover:text-zinc-700"
                        title="Yenile"
                    >
                        <RefreshCw className={cn("w-4 h-4", loading && "animate-spin")} />
                    </button>
                </div>
            </div>

            {error && (
                <div className="p-3 bg-red-50 dark:bg-red-900/20 text-red-600 rounded text-sm mb-4">
                    {error}
                </div>
            )}

            {loading ? (
                <div className="text-center text-zinc-500 text-sm py-6">
                    <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2" />
                    Yükleniyor...
                </div>
            ) : recentQuestions.length === 0 ? (
                <p className="text-zinc-500 text-sm">Henüz soru bulunamadı.</p>
            ) : (
                <div className="space-y-6">
                    {Object.entries(grouped).map(([source, categories]) => (
                        <div key={source} className="space-y-3">
                            <div className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
                                {source}
                            </div>
                            <div className="space-y-2">
                                {Object.entries(categories).map(([category, items]) => {
                                    const groupKey = `${source}::${category}`
                                    const isOpen = openGroups[groupKey] ?? true
                                    return (
                                        <div
                                            key={groupKey}
                                            className="border border-zinc-200 dark:border-zinc-800 rounded"
                                        >
                                            <button
                                                onClick={() => toggleGroup(groupKey)}
                                                className="w-full flex items-center justify-between px-3 py-2 bg-zinc-50 dark:bg-zinc-800/60 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-left"
                                            >
                                                <div className="flex items-center gap-2">
                                                    <span className="text-xs text-zinc-400">
                                                        {isOpen ? "-" : "+"}
                                                    </span>
                                                    <span className="text-sm font-medium text-zinc-800 dark:text-zinc-100">
                                                        {category}
                                                    </span>
                                                </div>
                                                <span className="text-xs text-zinc-500">{items.length} soru</span>
                                            </button>
                                            {isOpen && (
                                                <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
                                                    {items.map((item) => (
                                                        <div key={item.id} className="px-3 py-2">
                                                            <div className="text-xs text-zinc-500 mb-1">
                                                                {item.topic || "Konu yok"} • {formatDate(item.created_at)}
                                                            </div>
                                                            <div className="flex items-start justify-between gap-3">
                                                                <div className="text-sm text-zinc-900 dark:text-zinc-100 flex-1 whitespace-pre-wrap">
                                                                    {openQuestions[item.id]
                                                                        ? item.question_text
                                                                        : truncate(item.question_text)}
                                                                </div>
                                                                <button
                                                                    onClick={() => toggleQuestion(item.id)}
                                                                    className="text-xs text-blue-600 hover:text-blue-700 shrink-0"
                                                                >
                                                                    {openQuestions[item.id] ? "Kapat" : "Detay"}
                                                                </button>
                                                            </div>

                                                            {openQuestions[item.id] && (
                                                                <div className="mt-3 space-y-3">
                                                                    {Array.isArray(item.options) && item.options.length > 0 && (
                                                                        <div className="space-y-1">
                                                                            {item.options.map((opt, idx) => {
                                                                                const isCorrect = item.correct_answer_index === idx
                                                                                return (
                                                                                    <div
                                                                                        key={`${item.id}-opt-${idx}`}
                                                                                        className={cn(
                                                                                            "text-sm px-2 py-1 rounded border",
                                                                                            isCorrect
                                                                                                ? "border-green-400 bg-green-50 text-green-700"
                                                                                                : "border-zinc-200 dark:border-zinc-800"
                                                                                        )}
                                                                                    >
                                                                                        <span className="font-semibold mr-2">
                                                                                            {renderOptionLabel(opt, idx)}.
                                                                                        </span>
                                                                                        {renderOptionText(opt)}
                                                                                    </div>
                                                                                )
                                                                            })}
                                                                        </div>
                                                                    )}

                                                                    {(() => {
                                                                        const explanationNode = renderExplanation(item.explanation_data)
                                                                        if (!explanationNode) return null
                                                                        return (
                                                                            <div className="rounded border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-800/50 p-2">
                                                                                <div className="text-xs font-semibold text-zinc-500 mb-1">
                                                                                    Açıklama
                                                                                </div>
                                                                                {explanationNode}
                                                                            </div>
                                                                        )
                                                                    })()}

                                                                    {Array.isArray(item.tags) && item.tags.length > 0 && (
                                                                        <div className="flex flex-wrap gap-1">
                                                                            {item.tags.map((tag, idx) => (
                                                                                <span
                                                                                    key={`${item.id}-tag-${idx}`}
                                                                                    className="text-xs px-2 py-0.5 rounded-full bg-zinc-200 dark:bg-zinc-700 text-zinc-700 dark:text-zinc-200"
                                                                                >
                                                                                    {tag}
                                                                                </span>
                                                                            ))}
                                                                        </div>
                                                                    )}
                                                                </div>
                                                            )}
                                                        </div>
                                                    ))}
                                                </div>
                                            )}
                                        </div>
                                    )
                                })}
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </section>
    )
}
