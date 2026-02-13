"use client"

import { useState, useEffect } from "react"
import { X, Send, AlertTriangle } from "lucide-react"
import { submitFeedback } from "../lib/api"
import { cn } from "../lib/utils"

interface FeedbackDialogProps {
    isOpen: boolean
    onClose: () => void
    questionId: number
}

interface FeedbackShortcut {
    id: string
    label: string
    text: string
}

const STORAGE_KEY = "medquiz_feedback_shortcuts"

const DEFAULT_SHORTCUTS: FeedbackShortcut[] = [
    {
        id: "missing_context",
        label: "Bağlam eksik",
        text: "Soru yeterince bağlam sunmuyor; kaynak ve hipotezi netleştirelim."
    },
    {
        id: "incorrect_answer",
        label: "Hatalı cevap",
        text: "Doğru cevap metinde açık değil ya da seçeneklerle uyuşmuyor."
    },
    {
        id: "typo_short",
        label: "Yazım hatası",
        text: "Metinde yazım/gramer hatası bulunuyor."
    }
]

const FEEDBACK_TYPES = [
    { id: "wrong_answer", label: "Hatalı Cevap" },
    { id: "bad_explanation", label: "Kötü Açıklama" },
    { id: "typo", label: "Yazım Hatası" },
    { id: "other", label: "Diğer" }
]

export function FeedbackDialog({ isOpen, onClose, questionId }: FeedbackDialogProps) {
    const [type, setType] = useState(FEEDBACK_TYPES[0].id)
    const [description, setDescription] = useState("")
    const [submitting, setSubmitting] = useState(false)
    const [success, setSuccess] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [shortcuts, setShortcuts] = useState<FeedbackShortcut[]>(
        () => DEFAULT_SHORTCUTS.map(shortcut => ({ ...shortcut }))
    )
    const [showShortcutForm, setShowShortcutForm] = useState(false)
    const [newShortcutLabel, setNewShortcutLabel] = useState("")
    const [newShortcutText, setNewShortcutText] = useState("")

    useEffect(() => {
        if (typeof window === "undefined") return
        const stored = window.localStorage.getItem(STORAGE_KEY)
        if (!stored) return

        try {
            const parsed = JSON.parse(stored)
            if (Array.isArray(parsed) && parsed.length > 0) {
                setShortcuts(parsed)
            }
        } catch (err) {
            console.error("Failed to load feedback shortcuts", err)
        }
    }, [])

    const persistShortcuts = (items: FeedbackShortcut[]) => {
        if (typeof window === "undefined") return
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(items))
    }

    const generateShortcutId = () => {
        if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
            return crypto.randomUUID()
        }
        return `shortcut-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    }

    const handleAddShortcut = () => {
        const trimmedLabel = newShortcutLabel.trim()
        const trimmedText = newShortcutText.trim()
        if (!trimmedLabel || !trimmedText) return
        const newEntry: FeedbackShortcut = {
            id: generateShortcutId(),
            label: trimmedLabel,
            text: trimmedText
        }
        const updated = [...shortcuts, newEntry]
        setShortcuts(updated)
        persistShortcuts(updated)
        setNewShortcutLabel("")
        setNewShortcutText("")
        setShowShortcutForm(false)
    }

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault()
        setSubmitting(true)
        setError(null)

        try {
            await submitFeedback(questionId, type, description)
            setSuccess(true)
            setTimeout(() => {
                onClose()
                // Reset state after closing
                setTimeout(() => {
                    setSuccess(false)
                    setDescription("")
                    setType(FEEDBACK_TYPES[0].id)
                }, 300)
            }, 1500)
        } catch (err) {
            setError("Gönderilirken bir hata oluştu.")
        } finally {
            setSubmitting(false)
        }
    }

    if (!isOpen) return null

    return (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
            {/* Backdrop */}
            <div
                className="absolute inset-0 bg-black/50 backdrop-blur-sm transition-opacity"
                onClick={onClose}
            />

            {/* Modal */}
            <div className="relative bg-white dark:bg-zinc-900 rounded-xl shadow-2xl w-full max-w-md overflow-hidden animate-in fade-in zoom-in-95 duration-200">
                <div className="flex items-center justify-between p-4 border-b border-zinc-200 dark:border-zinc-800">
                    <h3 className="font-semibold flex items-center gap-2">
                        <AlertTriangle className="w-5 h-5 text-amber-500" />
                        Hata Bildir / Feedback
                    </h3>
                    <button
                        onClick={onClose}
                        className="p-1 hover:bg-zinc-100 dark:hover:bg-zinc-800 rounded-full transition-colors"
                    >
                        <X className="w-5 h-5 text-zinc-500" />
                    </button>
                </div>

                {success ? (
                    <div className="p-8 flex flex-col items-center text-center space-y-3">
                        <div className="w-12 h-12 bg-green-100 dark:bg-green-900/30 rounded-full flex items-center justify-center text-green-600 dark:text-green-400 text-2xl">
                            ✓
                        </div>
                        <h4 className="font-medium text-lg">Teşekkürler!</h4>
                        <p className="text-zinc-500 text-sm">Geri bildiriminiz alındı ve incelenecek.</p>
                    </div>
                ) : (
                    <form onSubmit={handleSubmit} className="p-4 space-y-4">
                        <div className="space-y-2">
                            <label className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
                                Sorun Türü
                            </label>
                            <div className="grid grid-cols-2 gap-2">
                                {FEEDBACK_TYPES.map(t => (
                                    <button
                                        key={t.id}
                                        type="button"
                                        onClick={() => setType(t.id)}
                                        className={cn(
                                            "px-3 py-2 rounded-lg text-sm border transition-all text-left",
                                            type === t.id
                                                ? "border-blue-500 bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300 ring-1 ring-blue-500"
                                                : "border-zinc-200 dark:border-zinc-700 hover:border-zinc-300 dark:hover:border-zinc-600"
                                        )}
                                    >
                                        {t.label}
                                    </button>
                                ))}
                            </div>
                        </div>

                        <div className="space-y-2">
                            <div className="flex items-center justify-between">
                                <label className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
                                    Kısayollar
                                </label>
                                <button
                                    type="button"
                                    onClick={() => setShowShortcutForm(prev => !prev)}
                                    className="text-xs font-medium text-blue-600 hover:text-blue-800 dark:text-blue-400 dark:hover:text-blue-300 transition-colors"
                                >
                                    {showShortcutForm ? "İptal" : "Kısayol Ekle"}
                                </button>
                            </div>
                            <div className="flex flex-wrap gap-2">
                                {shortcuts.map(shortcut => (
                                    <button
                                        key={shortcut.id}
                                        type="button"
                                        onClick={() => setDescription(shortcut.text)}
                                        className="px-3 py-1 text-xs rounded-full border border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
                                    >
                                        {shortcut.label}
                                    </button>
                                ))}
                            </div>
                            {showShortcutForm && (
                                <div className="space-y-2 p-3 rounded-lg border border-dashed border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-900/40">
                                    <input
                                        value={newShortcutLabel}
                                        onChange={(e) => setNewShortcutLabel(e.target.value)}
                                        placeholder="Kısayol etiketi"
                                        className="w-full text-sm px-2 py-1 rounded border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                                    />
                                    <textarea
                                        value={newShortcutText}
                                        onChange={(e) => setNewShortcutText(e.target.value)}
                                        placeholder="Kısayol açıklaması (tıklandığında burası açıklamaya yazılacak)"
                                        className="w-full text-sm px-2 py-1 rounded border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
                                        rows={2}
                                    />
                                    <div className="flex justify-end">
                                        <button
                                            type="button"
                                            onClick={handleAddShortcut}
                                            disabled={!newShortcutLabel.trim() || !newShortcutText.trim()}
                                            className="px-3 py-1 text-xs font-semibold rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
                                        >
                                            Kaydet
                                        </button>
                                    </div>
                                </div>
                            )}
                            <p className="text-xs text-zinc-500 dark:text-zinc-400">
                                Kısayol butonuna basınca açıklama otomatik olarak doldurulur.
                            </p>
                        </div>

                        <div className="space-y-2">
                            <label className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
                                Açıklama (İsteğe bağlı)
                            </label>
                            <textarea
                                value={description}
                                onChange={(e) => setDescription(e.target.value)}
                                placeholder="Daha fazla detay ekleyin..."
                                className="w-full h-24 px-3 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
                            />
                        </div>

                        {error && (
                            <div className="text-red-500 text-sm bg-red-50 dark:bg-red-900/10 p-2 rounded">
                                {error}
                            </div>
                        )}

                        <div className="flex justify-end pt-2">
                            <button
                                type="submit"
                                disabled={submitting}
                                className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-medium shadow-sm transition-colors disabled:opacity-50"
                            >
                                {submitting ? (
                                    <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                                ) : (
                                    <Send className="w-4 h-4" />
                                )}
                                Gönder
                            </button>
                        </div>
                    </form>
                )}
            </div>
        </div>
    )
}
