"use client"

import { useState, useEffect } from "react"
import { ChevronRight, ChevronDown, BookOpen, Folder, FileText, Package, Zap } from "lucide-react"
import { cn } from "../lib/utils"

interface SubSegment {
    title: string
    file: string
    page_count: number
    pages: [number, number]
    question_count?: number
    source_pdfs_list?: string[]
    merged_topics?: string[]
}

interface Segment {
    title: string
    file: string
    page_count: number
    pages_raw: [number, number]
    sub_segments: SubSegment[]
    question_count?: number
}

interface Volume {
    name: string
    source: string
    segments: Segment[]
}

interface Subject {
    volumes: Volume[]
}

interface SelectedPdf {
    title: string
    file: string
    pageCount: number
    source: string  // e.g., "Anatomi", "Farmakoloji"
    mainHeader?: string // The main topic/category key (e.g., "Hücre ve Organellerin Görevleri")
    existingQuestionCount?: number
    sourcePdfsList?: string[]
    mergedTopics?: string[]
}

interface GenerationSidebarProps {
    onSelectionChange: (selected: SelectedPdf[]) => void
    selectedPdfs: SelectedPdf[]
    onAutoChunkRequest?: (segmentTitle: string, source: string, subSegments: { title: string; file: string; page_count: number; source_pdfs_list?: string[]; merged_topics?: string[] }[], totalPages: number) => void
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "/api"

export function GenerationSidebar({ onSelectionChange, selectedPdfs, onAutoChunkRequest }: GenerationSidebarProps) {
    const [manifests, setManifests] = useState<Record<string, Subject>>({})
    const [loading, setLoading] = useState(true)
    const [expandedSubjects, setExpandedSubjects] = useState<Set<string>>(new Set())
    const [expandedVolumes, setExpandedVolumes] = useState<Set<string>>(new Set())
    const [expandedSegments, setExpandedSegments] = useState<Set<string>>(new Set())

    useEffect(() => {
        async function fetchManifests() {
            try {
                // Avoid stale library view (browser/edge caches can keep old manifests after PDF moves)
                const res = await fetch(`${API_BASE}/pdfs/manifests`, { cache: "no-store" })
                const text = await res.text()
                let data: any
                try {
                    data = JSON.parse(text)
                } catch {
                    throw new Error(`Failed to parse manifests JSON (status ${res.status}): ${text.slice(0, 200)}`)
                }
                if (!res.ok) {
                    const msg = data?.detail || data?.error || text
                    throw new Error(`Failed to fetch manifests (status ${res.status}): ${String(msg).slice(0, 200)}`)
                }
                setManifests(data.subjects || {})
            } catch (error) {
                console.error("Failed to fetch manifests:", error)
            } finally {
                setLoading(false)
            }
        }
        fetchManifests()
    }, [])

    const toggleSubject = (subject: string) => {
        const newSet = new Set(expandedSubjects)
        if (newSet.has(subject)) {
            newSet.delete(subject)
        } else {
            newSet.add(subject)
        }
        setExpandedSubjects(newSet)
    }

    const toggleVolume = (key: string) => {
        const newSet = new Set(expandedVolumes)
        if (newSet.has(key)) {
            newSet.delete(key)
        } else {
            newSet.add(key)
        }
        setExpandedVolumes(newSet)
    }

    const toggleSegment = (key: string) => {
        const newSet = new Set(expandedSegments)
        if (newSet.has(key)) {
            newSet.delete(key)
        } else {
            newSet.add(key)
        }
        setExpandedSegments(newSet)
    }

    const isSelected = (file: string) => selectedPdfs.some(p => p.file === file)

    // --- CONSTRAINT HELPERS ---

    // Returns the "Context ID" (Source + Main Header Key) of the current selection
    // Returns null if nothing is selected or if multiple disparate items were somehow selected (shouldn't happen with this logic)
    const getActiveContext = () => {
        if (selectedPdfs.length === 0) return null
        // We assume the first item defines the context
        const first = selectedPdfs[0]

        // We need to find the parent segment for this file to know the "Main Header"
        // Since we don't store parent info on SelectedPdf, we have to find it in the manifest.
        // Optimization: We could store it, but searching manifest is acceptable for small list.

        for (const [subjName, subj] of Object.entries(manifests)) {
            if (subjName !== first.source) continue

            for (const vol of subj.volumes) {
                for (const seg of vol.segments) {
                    // Check if it's the main segment itself
                    if (seg.file === first.file) {
                        return { source: subjName, mainHeader: seg.title } // Context is this main header
                    }
                    // Check if it's a sub-segment
                    const subMatch = seg.sub_segments.find(s => s.file === first.file)
                    if (subMatch) {
                        return { source: subjName, mainHeader: seg.title } // Context is the parent main header
                    }
                }
            }
        }
        return null
    }

    const activeContext = getActiveContext()

    // Check if an item is selectable based on active context
    const isSelectionDisabled = (source: string, mainHeaderTitle: string) => {
        if (!activeContext) return false // Nothing selected, everything open

        // Must match Source (Lesson)
        if (activeContext.source !== source) return true

        // Must match Main Header (Segment)
        if (activeContext.mainHeader !== mainHeaderTitle) return true

        return false
    }

    const handleSegmentClick = (segment: Segment, source: string) => {
        // If disabled, do nothing
        if (isSelectionDisabled(source, segment.title)) return

        const pdf: SelectedPdf = {
            title: segment.title,
            file: segment.file,
            pageCount: segment.page_count,
            source: source,
            mainHeader: segment.title, // When selecting a main segment, it IS the main header
            existingQuestionCount: segment.question_count
        }

        if (isSelected(segment.file)) {
            onSelectionChange(selectedPdfs.filter(p => p.file !== segment.file))
        } else {
            // If we are selecting a Main Segment, it implies clearing any existing sub-segment selection 
            // OR treating it as the single source.
            // Usually, mixing a Main Header + its own Sub-segment is redundant used together?
            // User's rule: "selection must be only on following subheaders"
            // Let's allow simple toggle for now, context lock prevents mixing with others.
            onSelectionChange([...selectedPdfs, pdf])
        }
    }

    const handleSubSegmentClick = (clickedSub: SubSegment, source: string, parentTitle: string, index: number, allSubSegments: SubSegment[]) => {
        // If disabled, do nothing
        if (isSelectionDisabled(source, parentTitle)) return

        // Helpers to create a SelectedPdf object
        const createPdf = (sub: SubSegment): SelectedPdf => ({
            title: sub.title,
            file: sub.file,
            pageCount: sub.page_count,
            source: source,
            mainHeader: parentTitle,
            existingQuestionCount: sub.question_count,
            sourcePdfsList: sub.source_pdfs_list,
            mergedTopics: sub.merged_topics
        })

        const clickedPdf = createPdf(clickedSub)
        const isClickedSelected = isSelected(clickedSub.file)

        // Filter out any selections that belong to THIS context (Source + Main Header)
        // We need to know which indices are currently selected
        const currentContextSelections = selectedPdfs.filter(p =>
            p.source === source && p.mainHeader === parentTitle
        )

        // Map current selections to their indices in the allSubSegments array
        // optimization: create a set of file paths for O(1) lookup
        const selectedFilesSet = new Set(currentContextSelections.map(p => p.file))
        const selectedIndices = allSubSegments
            .map((s, i) => selectedFilesSet.has(s.file) ? i : -1)
            .filter(i => i !== -1)
            .sort((a, b) => a - b)

        let newSelection = [...selectedPdfs]

        if (isClickedSelected) {
            // --- DESELECTION LOGIC (TRIM TAIL) ---
            // If we deselect an item, we must deselect it AND everything after it (or before it if it was min)
            // User rule verification: "block gaps" -> usually implies creating a solid block.
            // Convention: If I uncheck a middle item 2 in 1-2-3-4, I usually expect 3-4 to go away (keep 1), or 1 to go away (keep 3-4).
            // Let's go with "Keep Start" (Trim After).

            // Remove the clicked item AND any item with index > clicked index
            // Actually, simply keeping everything < index is the safest "Trim Tail" approach.

            // However, we must only affect items in THIS context.
            const keptInContext = currentContextSelections.filter(p => {
                // Find index of this selected pdf
                const pIndex = allSubSegments.findIndex(s => s.file === p.file)
                if (pIndex === -1) return false // Should not happen
                return pIndex < index // Keep only those BEFORE the clicked one
            })

            // Re-merge: (All OTHER contexts) + (Kept in THIS context)
            const otherContexts = selectedPdfs.filter(p => p.source !== source || p.mainHeader !== parentTitle)
            newSelection = [...otherContexts, ...keptInContext]

        } else {
            // --- SELECTION LOGIC (FILL GAPS) ---
            // If nothing selected, just select it.
            // If something selected, select range from Min(Selected) to Index OR Max(Selected) to Index

            if (selectedIndices.length === 0) {
                newSelection.push(clickedPdf)
            } else {
                const minSel = selectedIndices[0]
                const maxSel = selectedIndices[selectedIndices.length - 1]

                // Determine new range
                const start = Math.min(minSel, index)
                const end = Math.max(maxSel, index)

                // Select everything in [start, end]
                // We wipe current context selections and replace with this new range to be clean
                const rangePdfs = []
                for (let i = start; i <= end; i++) {
                    rangePdfs.push(createPdf(allSubSegments[i]))
                }

                const otherContexts = selectedPdfs.filter(p => p.source !== source || p.mainHeader !== parentTitle)
                newSelection = [...otherContexts, ...rangePdfs]
            }
        }

        onSelectionChange(newSelection)
    }

    if (loading) {
        return (
            <div className="p-4 text-center text-zinc-400">
                <Package className="w-8 h-8 mx-auto mb-2 animate-pulse" />
                Yükleniyor...
            </div>
        )
    }

    return (
        <div className="h-full overflow-y-auto p-4 no-scrollbar">
            <h2 className="text-lg font-bold mb-4 flex items-center gap-2">
                <Package className="w-5 h-5 text-purple-500" />
                PDF Kaynakları
            </h2>

            <p className="text-xs text-zinc-500 mb-4">
                Soru üretmek için içerik seçin. Birden fazla alt bölüm seçebilirsiniz.
            </p>

            <div className="space-y-1">
                {Object.entries(manifests).map(([subjectName, subject]) => (
                    <div key={subjectName}>
                        {/* Subject Header */}
                        <button
                            onClick={() => toggleSubject(subjectName)}
                            className="w-full flex items-center gap-2 py-2 px-2 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 text-left"
                        >
                            {expandedSubjects.has(subjectName)
                                ? <ChevronDown className="w-4 h-4 text-zinc-400" />
                                : <ChevronRight className="w-4 h-4 text-zinc-400" />
                            }
                            <BookOpen className="w-4 h-4 text-blue-500" />
                            <span className="font-medium">{subjectName}</span>
                            <span className="ml-auto text-xs text-zinc-400">
                                {subject.volumes.length} cilt
                            </span>
                        </button>

                        {/* Volumes */}
                        {expandedSubjects.has(subjectName) && (
                            <div className="ml-4 border-l border-zinc-200 dark:border-zinc-700">
                                {subject.volumes.map((volume, vIdx) => {
                                    const volumeKey = `${subjectName}-${volume.name}`
                                    return (
                                        <div key={volume.name} className="pl-4">
                                            {/* Volume Header */}
                                            <button
                                                onClick={() => toggleVolume(volumeKey)}
                                                className="w-full flex items-center gap-2 py-1.5 px-2 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 text-left text-sm"
                                            >
                                                {expandedVolumes.has(volumeKey)
                                                    ? <ChevronDown className="w-3 h-3 text-zinc-400" />
                                                    : <ChevronRight className="w-3 h-3 text-zinc-400" />
                                                }
                                                <Folder className="w-3 h-3 text-yellow-500" />
                                                <span className="truncate">Cilt {vIdx + 1}</span>
                                            </button>

                                            {/* Segments (Main Headers) */}
                                            {expandedVolumes.has(volumeKey) && (
                                                <div className="ml-4 border-l border-zinc-200 dark:border-zinc-700">
                                                    {volume.segments.map((segment, sIdx) => {
                                                        const segmentKey = `${volumeKey}-${segment.title}`
                                                        const hasSubSegments = segment.sub_segments.length > 0
                                                        const isMainSelected = isSelected(segment.file)

                                                        const isDisabled = isSelectionDisabled(subjectName, segment.title)

                                                        // Calculate total sub-segment pages for auto-chunk eligibility
                                                        const subSegmentTotalPages = hasSubSegments
                                                            ? segment.sub_segments.reduce((sum, s) => sum + s.page_count, 0)
                                                            : 0
                                                        const showAutoChunk = hasSubSegments && subSegmentTotalPages > 20 && onAutoChunkRequest

                                                        return (
                                                            <div key={sIdx} className="pl-2">
                                                                {/* Main Segment */}
                                                                <div className="flex items-center gap-1">
                                                                    {hasSubSegments && (
                                                                        <button
                                                                            onClick={() => toggleSegment(segmentKey)}
                                                                            className="p-1"
                                                                        >
                                                                            {expandedSegments.has(segmentKey)
                                                                                ? <ChevronDown className="w-3 h-3 text-zinc-400" />
                                                                                : <ChevronRight className="w-3 h-3 text-zinc-400" />
                                                                            }
                                                                        </button>
                                                                    )}
                                                                    <div
                                                                        onClick={() => !isDisabled && handleSegmentClick(segment, subjectName)}
                                                                        className={cn(
                                                                            "flex-1 flex items-center gap-1 py-1 px-2 rounded text-left text-xs transition-all cursor-pointer",
                                                                            isDisabled ? "opacity-30 cursor-not-allowed" : "hover:bg-zinc-100 dark:hover:bg-zinc-800",
                                                                            isMainSelected && "bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300"
                                                                        )}
                                                                    >
                                                                        <FileText className={cn(
                                                                            "w-3 h-3 flex-shrink-0",
                                                                            isMainSelected ? "text-purple-500" : "text-zinc-400"
                                                                        )} />
                                                                        <span className="truncate">{segment.title}</span>
                                                                        <div className="ml-auto flex items-center gap-1">
                                                                            {showAutoChunk && (
                                                                                <button
                                                                                    onClick={(e) => {
                                                                                        e.stopPropagation()
                                                                                        onAutoChunkRequest(
                                                                                            segment.title,
                                                                                            subjectName,
                                                                                            segment.sub_segments.map(s => ({
                                                                                                title: s.title,
                                                                                                file: s.file,
                                                                                                page_count: s.page_count,
                                                                                                source_pdfs_list: s.source_pdfs_list,
                                                                                                merged_topics: s.merged_topics
                                                                                            })),
                                                                                            subSegmentTotalPages
                                                                                        )
                                                                                    }}
                                                                                    className="flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 hover:bg-amber-200 dark:hover:bg-amber-900/50 transition-colors text-[10px] font-semibold"
                                                                                    title="Otomatik parçala ve soru üret"
                                                                                >
                                                                                    <Zap className="w-3 h-3" />
                                                                                    Parçala
                                                                                </button>
                                                                            )}
                                                                            <span className={cn(
                                                                                "text-xs px-1.5 py-0.5 rounded",
                                                                                segment.page_count <= 20
                                                                                    ? "bg-green-100 text-green-600 dark:bg-green-900/30 dark:text-green-400"
                                                                                    : "bg-orange-100 text-orange-600 dark:bg-orange-900/30 dark:text-orange-400"
                                                                            )}>
                                                                                {segment.page_count}s
                                                                            </span>
                                                                            {(segment.question_count || 0) > 0 && (
                                                                                <span className="text-xs px-1.5 py-0.5 rounded bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400">
                                                                                    {segment.question_count} soru
                                                                                </span>
                                                                            )}
                                                                        </div>
                                                                    </div>
                                                                </div>

                                                                {/* Sub-Segments */}
                                                                {expandedSegments.has(segmentKey) && hasSubSegments && (
                                                                    <div className="ml-6 border-l border-zinc-200 dark:border-zinc-700 pl-2 py-1 space-y-0.5">
                                                                        {segment.sub_segments.map((sub, subIdx) => {
                                                                            const isSubSelected = isSelected(sub.file)
                                                                            // Sub-segment is part of this segment, so we check using Parent's title
                                                                            const isSubDisabled = isSelectionDisabled(subjectName, segment.title)

                                                                            return (
                                                                                <button
                                                                                    key={subIdx}
                                                                                    onClick={() => handleSubSegmentClick(sub, subjectName, segment.title, subIdx, segment.sub_segments)}
                                                                                    disabled={isSubDisabled}
                                                                                    className={cn(
                                                                                        "w-full flex items-center gap-1 py-1 px-2 rounded text-left text-xs transition-all",
                                                                                        isSubDisabled && "opacity-30 cursor-not-allowed",
                                                                                        isSubSelected
                                                                                            ? "bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300"
                                                                                            : "hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-600 dark:text-zinc-400"
                                                                                    )}
                                                                                >
                                                                                    <span className={cn(
                                                                                        "w-4 h-4 flex items-center justify-center rounded text-[10px] flex-shrink-0",
                                                                                        isSubSelected
                                                                                            ? "bg-purple-200 dark:bg-purple-800"
                                                                                            : "bg-zinc-200 dark:bg-zinc-700"
                                                                                    )}>
                                                                                        {subIdx + 1}
                                                                                    </span>
                                                                                    <span className="truncate">{sub.title}</span>
                                                                                    <div className="ml-auto flex items-center gap-1">
                                                                                        <span className="text-zinc-400">
                                                                                            {sub.page_count}s
                                                                                        </span>
                                                                                        {(sub.question_count || 0) > 0 && (
                                                                                            <span className="text-blue-500 font-medium">
                                                                                                {sub.question_count}
                                                                                            </span>
                                                                                        )}
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
                        )}
                    </div>
                ))}

            </div>


        </div>
    )
}
