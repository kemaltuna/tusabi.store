"use client"

import { cn } from "../lib/utils"
import { Sparkles, BookOpen, RefreshCw, Clock } from "lucide-react"

export type QuizMode = "standard" | "new_only" | "review_only" | "latest"

interface ModeOption {
    mode: QuizMode
    label: string
    icon: React.ReactNode
    description: string
    color: string
}

const baseModeOptions: ModeOption[] = [
    {
        mode: "new_only",
        label: "Yeni",
        icon: <Sparkles className="w-4 h-4" />,
        description: "Sadece yeni sorular",
        color: "bg-green-500/20 text-green-600 dark:text-green-400 border-green-500/30"
    },
    {
        mode: "standard",
        label: "Standart",
        icon: <BookOpen className="w-4 h-4" />,
        description: "Önce tekrar, sonra yeni",
        color: "bg-blue-500/20 text-blue-600 dark:text-blue-400 border-blue-500/30"
    },
    {
        mode: "review_only",
        label: "Tekrar",
        icon: <RefreshCw className="w-4 h-4" />,
        description: "Sadece tekrar kartları",
        color: "bg-purple-500/20 text-purple-600 dark:text-purple-400 border-purple-500/30"
    }
]

interface QuizModeSelectorProps {
    mode: QuizMode
    onChange: (mode: QuizMode) => void
    className?: string
    showLatest?: boolean
}

export function QuizModeSelector({ mode, onChange, className, showLatest = false }: QuizModeSelectorProps) {
    const modeOptions: ModeOption[] = showLatest
        ? [
            ...baseModeOptions,
            {
                mode: "latest" as QuizMode,
                label: "Son",
                icon: <Clock className="w-4 h-4" />,
                description: "En yeni sorular (admin)",
                color: "bg-amber-500/20 text-amber-700 dark:text-amber-400 border-amber-500/30"
            }
        ]
        : baseModeOptions

    return (
        <div className={cn("flex gap-2", className)}>
            {modeOptions.map((option) => (
                <button
                    key={option.mode}
                    onClick={() => onChange(option.mode)}
                    className={cn(
                        "flex items-center gap-2 px-3 py-2 rounded-lg border transition-all whitespace-nowrap shrink-0",
                        mode === option.mode
                            ? option.color + " border-current font-medium"
                            : "bg-zinc-100 dark:bg-zinc-800 border-transparent text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300"
                    )}
                    title={option.description}
                >
                    {option.icon}
                    <span className="text-sm">{option.label}</span>
                </button>
            ))}
        </div>
    )
}
