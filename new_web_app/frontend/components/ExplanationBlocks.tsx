"use client"

import ReactMarkdown from "react-markdown"
import rehypeRaw from "rehype-raw"
import React from "react"
import { cn } from "../lib/utils"

// Types for explanation blocks
interface ExplanationBlock {
    type: "heading" | "markdown" | "callout" | "numbered_steps" | "mini_ddx" | "table"
    text?: string
    title?: string
    level?: number
    style?: "key_clues" | "exam_trap" | "clinical_pearl" | "warning"
    items?: (string | { text?: string; option_id?: string; label?: string; analysis?: string; why_wrong?: string; would_be_correct_if?: string; best_discriminator?: string })[]
    steps?: string[]
    headers?: string[]
    rows?: { entity: string; cells: string[] }[]
}

interface ExplanationData {
    blocks?: ExplanationBlock[]
    main_mechanism?: string
    distractor_analysis?: string | string[]
}

// Style configs for callouts
const calloutStyles = {
    key_clues: { bg: "bg-blue-50 dark:bg-blue-900/20", border: "border-l-4 border-blue-500", icon: "🔑" },
    exam_trap: { bg: "bg-red-50 dark:bg-red-900/20", border: "border-l-4 border-red-500", icon: "⚠️" },
    clinical_pearl: { bg: "bg-green-50 dark:bg-green-900/20", border: "border-l-4 border-green-500", icon: "💎" },
    warning: { bg: "bg-amber-50 dark:bg-amber-900/20", border: "border-l-4 border-amber-500", icon: "⚠️" }
}

function formatInlineListBreaks(text: string) {
    if (!text) return text
    let out = text
    // Break inline numeric/roman lists into new lines (e.g., "1) ... 2) ...", "I. ... II. ...")
    out = out.replace(/\s+(?=\d+\))/g, "\n")
    out = out.replace(/\s+(?=\d+\.\s)/g, "\n")
    out = out.replace(/\s+(?=(?:I|II|III|IV|V|VI|VII|VIII|IX|X)\)\s?)/g, "\n")
    out = out.replace(/\s+(?=(?:I|II|III|IV|V|VI|VII|VIII|IX|X)\.\s)/g, "\n")
    return out
}

// Helper to render inline markdown without dangerouslySetInnerHTML
function SimpleMarkdown({ text }: { text: string }) {
    if (!text) return null
    const normalized = formatInlineListBreaks(text)
    // Split by Markdown bold and italic tokens
    // Matches: **bold**, *italic*
    const parts = normalized.split(/(\*\*.*?\*\*|\*.*?\*)/g)

    return (
        <>
            {parts.map((part, i) => {
                if (part.startsWith("**") && part.endsWith("**")) {
                    return <strong key={i}>{part.slice(2, -2)}</strong>
                }
                if (part.startsWith("*") && part.endsWith("*")) {
                    return <em key={i}>{part.slice(1, -1)}</em>
                }
                return part
            })}
        </>
    )
}

export const ExplanationBlocks = React.memo(function ExplanationBlocks({ data, fontSize = "base" }: { data: ExplanationData | null | undefined, fontSize?: "sm" | "base" | "lg" | "xl" }) {
    if (!data) {
        return (
            <p className="text-zinc-500 italic">
                Bu soru için açıklama bulunamadı.
            </p>
        )
    }

    // Check if we have blocks-based structure
    if (data.blocks && data.blocks.length > 0) {
        return (
            <div className="space-y-4">
                {data.blocks.map((block, idx) => (
                    <RenderBlock key={idx} block={block} index={idx} fontSize={fontSize} />
                ))}
            </div>
        )
    }

    // Fallback to legacy format
    if (data.main_mechanism || data.distractor_analysis) {
        return <LegacyExplanation data={data} fontSize={fontSize} />
    }

    return (
        <p className="text-zinc-500 italic">
            Bu soru için detaylı açıklama bulunamadı.
        </p>
    )
})

function RenderBlock({ block, index, fontSize }: { block: ExplanationBlock; index: number; fontSize: "sm" | "base" | "lg" | "xl" }) {
    const sizeClasses = {
        sm: { base: "text-sm", small: "text-xs", heading: "text-base", prose: "prose-sm" },
        base: { base: "text-base", small: "text-sm", heading: "text-lg", prose: "prose-base" },
        lg: { base: "text-lg", small: "text-base", heading: "text-xl", prose: "prose-lg" },
        xl: { base: "text-xl", small: "text-lg", heading: "text-2xl", prose: "prose-xl" }
    }
    const styles = sizeClasses[fontSize]

    switch (block.type) {
        case "heading":
            const level = block.level || 3
            // Scale headings based on base size
            const headingClass = `font-bold mt-4 mb-2 text-zinc-900 dark:text-zinc-100 ${styles.heading}`

            if (level === 1) return <h1 key={index} className={`font-bold mt-6 mb-3 text-2xl ${fontSize === 'xl' ? 'text-3xl' : ''}`}>{block.text}</h1>
            if (level === 2) return <h2 key={index} className={`font-bold mt-5 mb-2 text-xl ${fontSize === 'xl' ? 'text-2xl' : ''}`}>{block.text}</h2>
            if (level === 4) return <h4 key={index} className={headingClass}>{block.text}</h4>
            if (level === 5) return <h5 key={index} className={headingClass}>{block.text}</h5>
            return <h3 key={index} className={headingClass}>{block.text}</h3>

        case "markdown":
            return (
                <div key={index} className={`prose dark:prose-invert max-w-none leading-relaxed break-words ${styles.prose}`}>
                    <ReactMarkdown rehypePlugins={[rehypeRaw]}>
                        {block.text || ""}
                    </ReactMarkdown>
                </div>
            )

        case "callout":
            const style = calloutStyles[block.style || "key_clues"]
            return (
                <div key={index} className={cn("p-4 rounded-lg my-3", style.bg, style.border)}>
                    <div className={cn("font-semibold mb-2 flex items-center gap-2", styles.base)}>
                        <span>{style.icon}</span>
                        <span>{block.title || "Not"}</span>
                    </div>
                    <ul className={cn("list-disc list-inside space-y-1", styles.base)}>
                        {block.items?.map((item, i) => {
                            const text = typeof item === "string" ? item : item.text || ""
                            return (
                                <li key={i} className="whitespace-pre-line">
                                    <SimpleMarkdown text={text} />
                                </li>
                            )
                        })}
                    </ul>
                </div>
            )

        case "numbered_steps":
            return (
                <div key={index} className="my-3">
                    <h4 className={cn("font-semibold mb-2", styles.base)}>{block.title || "Mekanizma"}</h4>
                    <ol className={cn("list-decimal list-inside space-y-1", styles.base)}>
                        {block.steps?.map((step, i) => (
                            <li key={i}>
                                <SimpleMarkdown text={step} />
                            </li>
                        ))}
                    </ol>
                </div>
            )

        case "mini_ddx":
            return (
                <div key={index} className="my-3">
                    <h4 className={cn("font-semibold mb-2", styles.base)}>{block.title || "Ayırıcı Tanı"}</h4>
                    <div className="space-y-3">
                        {block.items?.map((item, i) => {
                            if (typeof item === "string") return null
                            return (
                                <div key={i} className="p-3 border border-zinc-200 dark:border-zinc-700 rounded-lg bg-zinc-50 dark:bg-zinc-800/50">
                                    <p className={cn("font-medium mb-1 text-zinc-500", styles.small)}>
                                        Seçenek {item.option_id}
                                    </p>
                                    <p className={cn("font-medium mb-1", styles.base)}>
                                        {item.label}
                                    </p>
                                    {item.analysis && (
                                        <p className={cn("text-zinc-700 dark:text-zinc-300", styles.small)}>
                                            {item.analysis}
                                        </p>
                                    )}
                                    {item.why_wrong && (
                                        <p className={cn("text-red-600 dark:text-red-400 mt-1", styles.small)}>
                                            ❌ {item.why_wrong}
                                        </p>
                                    )}
                                    {item.would_be_correct_if && (
                                        <p className={cn("mt-1 text-green-600 dark:text-green-400", styles.small)}>
                                            ✅ {item.would_be_correct_if}
                                        </p>
                                    )}
                                    {item.best_discriminator && (
                                        <p className={cn("mt-1 text-blue-600 dark:text-blue-400", styles.small)}>
                                            🔑 {item.best_discriminator}
                                        </p>
                                    )}
                                </div>
                            )
                        })}
                    </div>
                </div>
            )

        case "table":
            return (
                <div key={index} className="my-3 overflow-x-auto touch-pan-x no-scrollbar">
                    <h4 className={cn("font-semibold mb-2", styles.base)}>{block.title || "Tablo"}</h4>
                    <table className={cn("min-w-full border border-zinc-300 dark:border-zinc-600", styles.small)}>
                        <thead>
                            <tr className="bg-zinc-100 dark:bg-zinc-800">
                                {block.headers?.map((h, i) => (
                                    <th key={i} className="px-3 py-2 text-left border-b border-zinc-300 dark:border-zinc-600 font-medium">
                                        {h}
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {block.rows?.map((row, ri) => (
                                <tr key={ri} className="border-b border-zinc-200 dark:border-zinc-700">
                                    <td className="px-3 py-2 font-medium">{row.entity}</td>
                                    {row.cells.map((cell, ci) => (
                                        <td key={ci} className="px-3 py-2">{cell}</td>
                                    ))}
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )

        default:
            return null
    }
}

function LegacyExplanation({ data, fontSize }: { data: ExplanationData, fontSize: "sm" | "base" | "lg" | "xl" }) {
    const sizeClasses = {
        sm: { base: "text-sm", prose: "prose-sm" },
        base: { base: "text-base", prose: "prose-base" },
        lg: { base: "text-lg", prose: "prose-lg" },
        xl: { base: "text-xl", prose: "prose-xl" }
    }
    const styles = sizeClasses[fontSize]

    return (
        <div className={cn("space-y-4 break-words", styles.base)}>
            {data.main_mechanism && (
                <div>
                    <h4 className="font-semibold mb-2">Mekanizma</h4>
                    <div className={cn("prose dark:prose-invert max-w-none", styles.prose)}>
                        <ReactMarkdown rehypePlugins={[rehypeRaw]}>
                            {data.main_mechanism}
                        </ReactMarkdown>
                    </div>
                </div>
            )}
            {data.distractor_analysis && (
                <div>
                    <h4 className="font-semibold mb-2">Neden Diğer Şıklar Yanlış</h4>
                    {typeof data.distractor_analysis === "string" ? (
                        <div className={cn("prose dark:prose-invert max-w-none", styles.prose)}>
                            <ReactMarkdown rehypePlugins={[rehypeRaw]}>
                                {data.distractor_analysis}
                            </ReactMarkdown>
                        </div>
                    ) : (
                        <ul className="list-disc list-inside">
                            {data.distractor_analysis.map((d, i) => (
                                <li key={i}>{d}</li>
                            ))}
                        </ul>
                    )}
                </div>
            )}
        </div>
    )
}
