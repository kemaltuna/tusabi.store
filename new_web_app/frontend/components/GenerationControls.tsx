"use client"

import { useState, useEffect, useCallback, useRef, useMemo } from "react"
import { Sparkles, Minus, Plus, Loader, ChevronDown, ChevronUp, Save, Star, Trash2, RotateCcw, Info, X, PlusCircle, GripVertical } from "lucide-react"
import { cn } from "../lib/utils"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "/api"

// Section metadata for display (default sections)
const DEFAULT_SECTION_META: Record<string, { label: string; description: string }> = {
    persona: { label: "👤 Persona", description: "AI'ın rolü ve uzmanlık alanı" },
    goal: { label: "🎯 Hedef", description: "Soru üretim hedefi ve kapsamı" },
    principles: { label: "📋 İlkeler", description: "Uyulması gereken temel kurallar" },
    format_rules: { label: "📐 Format Kuralları", description: "Soru formatı ve çıktı kuralları" },
    example: { label: "📝 Örnek Format", description: "Beklenen çıktı formatı örneği" },
    closing: { label: "🚀 Kapanış", description: "Son komut / yönerge" },
}

// Template variables reference
const TEMPLATE_VARS = [
    { var: "{persona_role}", desc: "Otomatik: ders adına göre uzman rolü" },
    { var: "{display_topic}", desc: "Seçili konu/kategori adı" },
    //{ var: "{topic}", desc: "Ham konu adı" }, // Deprecated
    { var: "{diff_text}", desc: "Zorluk seviyesi açıklaması" },
    { var: "{count}", desc: "Soru sayısı" },
    { var: "{total_history}", desc: "Toplam geçmiş soru sayısı" },
    { var: "{unique_titles_count}", desc: "Farklı başlık sayısı" },
    { var: "{history_summary}", desc: "Geçmiş başlık özeti" },
    { var: "{lesson_name}", desc: "Ders adı" },
]

// Difficulty level labels
const DIFFICULTY_LABELS: Record<string, string> = {
    "1": "Orta",
    "2": "Orta-Zor",
    "3": "Zor",
    "4": "Zor - Çok Zor",
}

interface SectionFavorite {
    id: number
    section_key: string
    name: string
    content: string
    created_at: string
}

interface PromptTemplate {
    id: number
    name: string
    sections: Record<string, string>
    is_default: boolean
    created_at: string
    updated_at: string
}

interface DifficultyTemplate {
    id: number
    name: string
    levels: Record<string, string>
    is_default: boolean
    created_at: string
}

interface GenerationControlsProps {
    selectedPdfs: { title: string; file: string; pageCount: number; source: string; mainHeader?: string; existingQuestionCount?: number }[]
    onGenerate: (count: number, difficulty: number, customPromptSections?: Record<string, string> | null, customDifficultyLevels?: Record<string, string> | null) => void
    onClear: () => void
    isGenerating: boolean
}

export function GenerationControls({
    selectedPdfs,
    onGenerate,
    onClear,
    isGenerating
}: GenerationControlsProps) {
    const [questionCount, setQuestionCount] = useState(10)
    const [difficulty, setDifficulty] = useState(1)
    const [multiplier, setMultiplier] = useState(1)

    // Prompt Editor State
    const [promptEditorOpen, setPromptEditorOpen] = useState(false)
    const [defaultSections, setDefaultSections] = useState<Record<string, string> | null>(null)
    const [defaultSectionOrder, setDefaultSectionOrder] = useState<string[]>([])
    const [customSections, setCustomSections] = useState<Record<string, string>>({})
    const [sectionOrder, setSectionOrder] = useState<string[]>([])
    const [enabledSections, setEnabledSections] = useState<Record<string, boolean>>({})

    // Difficulty Level Editor
    const [difficultyEditorOpen, setDifficultyEditorOpen] = useState(false)
    const [defaultDifficultyLevels, setDefaultDifficultyLevels] = useState<Record<string, string>>({})
    const [customDifficultyLevels, setCustomDifficultyLevels] = useState<Record<string, string>>({})

    // Difficulty Favorites State
    const [difficultyFavorites, setDifficultyFavorites] = useState<DifficultyTemplate[]>([])
    const [diffFavoritesOpen, setDiffFavoritesOpen] = useState(false)
    const [diffSaveName, setDiffSaveName] = useState("")
    const [showDiffSaveInput, setShowDiffSaveInput] = useState(false)

    // Custom Section Add
    const [showAddSection, setShowAddSection] = useState(false)
    const [newSectionKey, setNewSectionKey] = useState("")
    const [newSectionLabel, setNewSectionLabel] = useState("")

    // Custom section labels (for user-added sections)
    const [customSectionLabels, setCustomSectionLabels] = useState<Record<string, string>>({})

    // Favorites State (full template)
    const [favorites, setFavorites] = useState<PromptTemplate[]>([])
    const [favoritesOpen, setFavoritesOpen] = useState(false)
    const [saveName, setSaveName] = useState("")
    const [showSaveInput, setShowSaveInput] = useState(false)
    const [showVarRef, setShowVarRef] = useState(false)
    const didAutoLoadDefaultPromptRef = useRef(false)

    // Per-Section Favorites State
    const [sectionFavorites, setSectionFavorites] = useState<Record<string, SectionFavorite[]>>({})
    const [sectionFavOpen, setSectionFavOpen] = useState<Record<string, boolean>>({})
    const [sectionSaveName, setSectionSaveName] = useState<Record<string, string>>({})
    const [sectionShowSave, setSectionShowSave] = useState<Record<string, boolean>>({})

    const totalPages = selectedPdfs.reduce((sum, p) => sum + p.pageCount, 0)
    const totalExistingQuestions = selectedPdfs.reduce((sum, p) => sum + (p.existingQuestionCount || 0), 0)
    const isDifficultyModified = useMemo(() => (
        Object.keys(defaultDifficultyLevels).some(k => customDifficultyLevels[k] !== defaultDifficultyLevels[k])
    ), [customDifficultyLevels, defaultDifficultyLevels])

    // Fetch difficulty favorites
    const fetchDifficultyFavorites = useCallback(async () => {
        try {
            const token = localStorage.getItem("medquiz_token")
            const res = await fetch(`${API_BASE}/admin/difficulty-templates`, {
                headers: token ? { Authorization: `Bearer ${token}` } : {}
            })
            if (res.ok) {
                const data: DifficultyTemplate[] = await res.json()
                setDifficultyFavorites(data)

                // Auto-load default difficulty if available and not modified
                const defaultFav = data.find((f) => f.is_default)
                if (defaultFav && !isDifficultyModified) {
                    setCustomDifficultyLevels(prev =>
                        Object.keys(prev).length === 0 ? defaultFav.levels : prev
                    )
                }
            }
        } catch (e) { console.error("Failed to fetch difficulty favorites:", e) }
    }, [isDifficultyModified])

    const isModified = useMemo(() => {
        if (!defaultSections) return false
        return sectionOrder.some(key =>
            customSections[key] !== (defaultSections[key] ?? "") || !enabledSections[key]
        ) || sectionOrder.length !== defaultSectionOrder.length || sectionOrder.some((k, i) => k !== defaultSectionOrder[i])
    }, [customSections, defaultSections, enabledSections, sectionOrder, defaultSectionOrder])

    // Fetch full template favorites
    const fetchFavorites = useCallback(async (autoLoadDefault: boolean = false, defaultOrderOverride: string[] | null = null) => {
        try {
            const token = localStorage.getItem("medquiz_token")
            const res = await fetch(`${API_BASE}/admin/prompt-templates`, {
                headers: token ? { Authorization: `Bearer ${token}` } : {}
            })
            if (res.ok) {
                const data: PromptTemplate[] = await res.json()
                setFavorites(data)

                // Optionally auto-load default favorite during initial hydrate.
                const defaultFav = data.find(f => f.is_default)
                if (autoLoadDefault && defaultFav && !isModified) {
                    setCustomSections({ ...defaultFav.sections })
                    const order = Object.keys(defaultFav.sections)
                    const baseOrder = defaultOrderOverride && defaultOrderOverride.length > 0
                        ? defaultOrderOverride
                        : defaultSectionOrder
                    const merged = [...baseOrder]
                    order.forEach(k => { if (!merged.includes(k)) merged.push(k) })
                    setSectionOrder(merged)
                    const enabled: Record<string, boolean> = {}
                    merged.forEach(k => { enabled[k] = true })
                    setEnabledSections(enabled)
                }
            }
        } catch (e) { console.error("Failed to fetch favorites:", e) }
    }, [isModified, defaultSectionOrder]) // Added dependencies for deterministic initial hydrate

    // Fetch per-section favorites
    const fetchSectionFavorites = useCallback(async () => {
        try {
            const token = localStorage.getItem("medquiz_token")
            const res = await fetch(`${API_BASE}/admin/section-favorites`, {
                headers: token ? { Authorization: `Bearer ${token}` } : {}
            })
            if (res.ok) {
                const data: SectionFavorite[] = await res.json()
                const grouped: Record<string, SectionFavorite[]> = {}
                data.forEach(f => {
                    if (!grouped[f.section_key]) grouped[f.section_key] = []
                    grouped[f.section_key].push(f)
                })
                setSectionFavorites(grouped)
            }
        } catch (e) { console.error("Failed to fetch section favorites:", e) }
    }, [])

    // Fetch default sections on mount
    // Intentional one-time hydrate on mount; callbacks are used as imperative loaders.
    useEffect(() => {
        const fetchDefaults = async () => {
            try {
                const token = localStorage.getItem("medquiz_token")
                const res = await fetch(`${API_BASE}/admin/prompt-default-sections`, {
                    headers: token ? { Authorization: `Bearer ${token}` } : {}
                })
                if (res.ok) {
                    const data = await res.json()
                    setDefaultSections(data.sections)
                    const order = data.section_order || Object.keys(data.sections)
                    setDefaultSectionOrder(order)
                    setDefaultDifficultyLevels(data.difficulty_levels || {})
                    // Initialize prompt editor defaults only when no template has been loaded yet.
                    setCustomSections(prev => Object.keys(prev).length > 0 ? prev : { ...data.sections })
                    setSectionOrder(prev => prev.length > 0 ? prev : [...order])
                    setEnabledSections(prev => {
                        if (Object.keys(prev).length > 0) return prev
                        const enabled: Record<string, boolean> = {}
                        order.forEach((k: string) => { enabled[k] = true })
                        return enabled
                    })
                    // Initialize difficulty defaults only if not already populated.
                    setCustomDifficultyLevels(prev => (
                        Object.keys(prev).length > 0 ? prev : { ...(data.difficulty_levels || {}) }
                    ))
                    if (!didAutoLoadDefaultPromptRef.current) {
                        didAutoLoadDefaultPromptRef.current = true
                        fetchFavorites(true, order)
                    } else {
                        fetchFavorites(false)
                    }
                } else {
                    fetchFavorites(false)
                }
                // Fetch difficulty favorites after defaults logic
                fetchDifficultyFavorites()
                fetchSectionFavorites()
            } catch (e) {
                console.error("Failed to fetch default sections:", e)
                fetchFavorites(false)
                fetchSectionFavorites()
            }
        }
        fetchDefaults()
    }, []) // eslint-disable-line react-hooks/exhaustive-deps

    const handleSectionChange = (key: string, value: string) => {
        setCustomSections(prev => ({ ...prev, [key]: value }))
    }

    const toggleSection = (key: string) => {
        setEnabledSections(prev => ({ ...prev, [key]: !prev[key] }))
    }

    const resetToDefault = () => {
        if (defaultSections) {
            setCustomSections({ ...defaultSections })
            setSectionOrder([...defaultSectionOrder])
            const enabled: Record<string, boolean> = {}
            defaultSectionOrder.forEach(k => { enabled[k] = true })
            setEnabledSections(enabled)
            setCustomSectionLabels({})
        }
    }

    const resetDifficultyToDefault = () => {
        setCustomDifficultyLevels({ ...defaultDifficultyLevels })
    }

    const addCustomSection = () => {
        const key = newSectionKey.trim().toLowerCase().replace(/\s+/g, "_").replace(/[^a-z0-9_]/g, "")
        if (!key || sectionOrder.includes(key)) return
        setSectionOrder(prev => [...prev, key])
        setCustomSections(prev => ({ ...prev, [key]: "" }))
        setEnabledSections(prev => ({ ...prev, [key]: true }))
        setCustomSectionLabels(prev => ({ ...prev, [key]: newSectionLabel.trim() || key }))
        setNewSectionKey("")
        setNewSectionLabel("")
        setShowAddSection(false)
    }

    const removeSection = (key: string) => {
        // Only allow removing custom sections (not defaults)
        if (defaultSectionOrder.includes(key)) return
        setSectionOrder(prev => prev.filter(k => k !== key))
        setCustomSections(prev => { const n = { ...prev }; delete n[key]; return n })
        setEnabledSections(prev => { const n = { ...prev }; delete n[key]; return n })
        setCustomSectionLabels(prev => { const n = { ...prev }; delete n[key]; return n })
    }

    const getSectionLabel = (key: string): string => {
        if (customSectionLabels[key]) return `📌 ${customSectionLabels[key]}`
        return DEFAULT_SECTION_META[key]?.label || `📌 ${key}`
    }

    const getSectionDescription = (key: string): string => {
        return DEFAULT_SECTION_META[key]?.description || "Özel bölüm"
    }

    const loadFavorite = (template: PromptTemplate) => {
        setCustomSections({ ...template.sections })
        const order = Object.keys(template.sections)
        // Merge with default order: keep defaults first, then extras
        const merged = [...defaultSectionOrder]
        order.forEach(k => { if (!merged.includes(k)) merged.push(k) })
        setSectionOrder(merged)
        const enabled: Record<string, boolean> = {}
        merged.forEach(k => { enabled[k] = true })
        setEnabledSections(enabled)
        setFavoritesOpen(false)
    }

    const saveFavorite = async () => {
        if (!saveName.trim()) return
        try {
            const token = localStorage.getItem("medquiz_token")
            const sectionsToSave: Record<string, string> = {}
            sectionOrder.forEach(k => { if (enabledSections[k]) sectionsToSave[k] = customSections[k] || "" })
            await fetch(`${API_BASE}/admin/prompt-templates`, {
                method: "POST",
                headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
                body: JSON.stringify({ name: saveName.trim(), sections: sectionsToSave, is_default: false })
            })
            setSaveName(""); setShowSaveInput(false); fetchFavorites()
        } catch (e) { console.error("Failed to save favorite:", e) }
    }

    const toggleDefaultFavorite = async (template: PromptTemplate, e: React.MouseEvent) => {
        e.stopPropagation()
        try {
            const token = localStorage.getItem("medquiz_token")
            // Iterate all templates to unset default if needed? No, backend handles it.
            // Just update this template to is_default = !is_default (or just true if we only want to set)
            // Let's allow toggling off too.
            await fetch(`${API_BASE}/admin/prompt-templates/${template.id}`, {
                method: "PUT",
                headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
                body: JSON.stringify({
                    name: template.name,
                    sections: template.sections,
                    is_default: !template.is_default
                })
            })
            fetchFavorites()
        } catch (err) { console.error("Failed to toggle default favorite:", err) }
    }

    const deleteFavorite = async (id: number, e: React.MouseEvent) => {
        e.stopPropagation()
        try {
            const token = localStorage.getItem("medquiz_token")
            await fetch(`${API_BASE}/admin/prompt-templates/${id}`, {
                method: "DELETE", headers: token ? { Authorization: `Bearer ${token}` } : {}
            })
            fetchFavorites()
        } catch (err) { console.error("Failed to delete favorite:", err) }
    }

    // Per-section favorite helpers
    const saveSectionFavorite = async (sectionKey: string) => {
        const name = sectionSaveName[sectionKey]?.trim()
        if (!name || !customSections[sectionKey]) return
        try {
            const token = localStorage.getItem("medquiz_token")
            await fetch(`${API_BASE}/admin/section-favorites`, {
                method: "POST",
                headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
                body: JSON.stringify({ section_key: sectionKey, name, content: customSections[sectionKey] })
            })
            setSectionSaveName(prev => ({ ...prev, [sectionKey]: "" }))
            setSectionShowSave(prev => ({ ...prev, [sectionKey]: false }))
            fetchSectionFavorites()
        } catch (e) { console.error("Failed to save section favorite:", e) }
    }

    const deleteSectionFavorite = async (id: number, e: React.MouseEvent) => {
        e.stopPropagation()
        try {
            const token = localStorage.getItem("medquiz_token")
            await fetch(`${API_BASE}/admin/section-favorites/${id}`, {
                method: "DELETE", headers: token ? { Authorization: `Bearer ${token}` } : {}
            })
            fetchSectionFavorites()
        } catch (err) { console.error("Failed to delete section favorite:", err) }
    }

    // Difficulty Template Handlers
    const loadDifficultyFavorite = (fav: DifficultyTemplate) => {
        setCustomDifficultyLevels(fav.levels)
        setDiffFavoritesOpen(false)
    }

    const saveDifficultyFavorite = async () => {
        if (!diffSaveName.trim()) return
        try {
            const token = localStorage.getItem("medquiz_token")
            await fetch(`${API_BASE}/admin/difficulty-templates`, {
                method: "POST",
                headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
                body: JSON.stringify({ name: diffSaveName.trim(), levels: customDifficultyLevels, is_default: false })
            })
            setDiffSaveName("")
            setShowDiffSaveInput(false)
            fetchDifficultyFavorites()
        } catch (e) { console.error("Failed to save difficulty favorite:", e) }
    }

    const toggleDefaultDifficultyFavorite = async (fav: DifficultyTemplate, e: React.MouseEvent) => {
        e.stopPropagation()
        try {
            const token = localStorage.getItem("medquiz_token")
            await fetch(`${API_BASE}/admin/difficulty-templates/${fav.id}`, {
                method: "PUT",
                headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
                body: JSON.stringify({
                    name: fav.name,
                    levels: fav.levels,
                    is_default: !fav.is_default
                })
            })
            fetchDifficultyFavorites()
        } catch (err) { console.error("Failed to toggle default difficulty favorite:", err) }
    }

    const deleteDifficultyFavorite = async (id: number, e: React.MouseEvent) => {
        e.stopPropagation()
        try {
            const token = localStorage.getItem("medquiz_token")
            await fetch(`${API_BASE}/admin/difficulty-templates/${id}`, {
                method: "DELETE", headers: token ? { Authorization: `Bearer ${token}` } : {}
            })
            fetchDifficultyFavorites()
        } catch (err) { console.error("Failed to delete difficulty favorite:", err) }
    }

    const loadSectionFavorite = (sectionKey: string, fav: SectionFavorite) => {
        setCustomSections(prev => ({ ...prev, [sectionKey]: fav.content }))
        setSectionFavOpen(prev => ({ ...prev, [sectionKey]: false }))
    }

    const getActivePromptSections = (): Record<string, string> | null => {
        if (!isModified) return null
        const result: Record<string, string> = {}
        for (const key of sectionOrder) {
            result[key] = enabledSections[key] ? (customSections[key] || "") : ""
        }
        return result
    }

    const getActiveDifficultyLevels = (): Record<string, string> | null => {
        if (!isDifficultyModified) return null
        return { ...customDifficultyLevels }
    }

    const handleGenerate = async () => {
        if (selectedPdfs.length === 0) return
        const promptSections = getActivePromptSections()
        const diffLevels = getActiveDifficultyLevels()
        for (let i = 0; i < multiplier; i++) {
            onGenerate(questionCount, difficulty, promptSections, diffLevels)
            if (i < multiplier - 1) {
                await new Promise(resolve => setTimeout(resolve, 300))
            }
        }
    }

    return (
        <div className="bg-gradient-to-r from-purple-50 to-indigo-50 dark:from-purple-900/20 dark:to-indigo-900/20 rounded-xl p-6 border border-purple-200 dark:border-purple-800">
            <h3 className="text-lg font-bold mb-4 flex items-center gap-2">
                <Sparkles className="w-5 h-5 text-purple-500" />
                Soru Üretimi
            </h3>

            {/* Selected Content Summary */}
            <div className="mb-6 p-3 bg-white/50 dark:bg-black/20 rounded-lg">
                <div className="flex items-center justify-between mb-2">
                    <p className="text-sm text-zinc-600 dark:text-zinc-400">
                        Seçili İçerik ({selectedPdfs.length} bölüm, {totalPages} sayfa):
                    </p>
                    {totalExistingQuestions > 0 && (
                        <span className="text-xs px-2 py-0.5 bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400 rounded-full font-medium">
                            {totalExistingQuestions} mevcut soru
                        </span>
                    )}
                </div>
                {selectedPdfs.length === 0 ? (
                    <p className="text-sm text-zinc-400 italic">Sol menüden içerik seçin...</p>
                ) : (
                    <ul className="text-sm space-y-1 max-h-32 overflow-y-auto">
                        {selectedPdfs.map((pdf, idx) => (
                            <li key={idx} className="flex items-center gap-2">
                                <span className="w-5 h-5 bg-purple-200 dark:bg-purple-800 rounded text-xs flex items-center justify-center">{idx + 1}</span>
                                <span className="truncate flex-1">{pdf.title}</span>
                                <div className="flex items-center gap-2 text-zinc-400">
                                    <span>({pdf.pageCount}s)</span>
                                    {(pdf.existingQuestionCount || 0) > 0 && (
                                        <span className="text-blue-500 font-medium">[{pdf.existingQuestionCount} soru]</span>
                                    )}
                                </div>
                            </li>
                        ))}
                    </ul>
                )}
            </div>

            {/* Question Count Slider */}
            <div className="mb-4">
                <div className="flex items-center justify-between mb-2">
                    <label className="text-sm font-medium">Soru Sayısı (Her İşlem İçin)</label>
                    <div className="flex items-center gap-2">
                        <input
                            type="number"
                            value={questionCount}
                            onChange={(e) => setQuestionCount(Math.max(1, Math.min(200, parseInt(e.target.value) || 1)))}
                            className="w-16 text-center text-lg font-bold text-purple-600 bg-white dark:bg-zinc-800 border border-purple-200 dark:border-purple-700 rounded-lg px-2 py-0.5 focus:outline-none focus:ring-1 focus:ring-purple-500"
                            min={1}
                            max={200}
                        />
                    </div>
                </div>
                <div className="flex items-center gap-3">
                    <button onClick={() => setQuestionCount(Math.max(1, questionCount - 1))} className="w-8 h-8 rounded-full bg-zinc-200 dark:bg-zinc-700 flex items-center justify-center hover:bg-zinc-300 dark:hover:bg-zinc-600">
                        <Minus className="w-4 h-4" />
                    </button>
                    <input type="range" min="1" max="200" value={questionCount} onChange={(e) => setQuestionCount(parseInt(e.target.value))}
                        className="flex-1 h-2 bg-zinc-200 dark:bg-zinc-700 rounded-lg appearance-none cursor-pointer accent-purple-500" />
                    <button onClick={() => setQuestionCount(Math.min(200, questionCount + 1))} className="w-8 h-8 rounded-full bg-zinc-200 dark:bg-zinc-700 flex items-center justify-center hover:bg-zinc-300 dark:hover:bg-zinc-600">
                        <Plus className="w-4 h-4" />
                    </button>
                </div>
            </div>

            {/* Multiplier Selector */}
            <div className="mb-4">
                <div className="flex items-center justify-between mb-2">
                    <label className="text-sm font-medium">Tekrar Sayısı (Part)</label>
                    <span className="text-sm font-medium text-purple-600">
                        {multiplier} x {questionCount} = {multiplier * questionCount} Toplam Soru
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

            {/* Difficulty Slider */}
            <div className="mb-6">
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

            {/* ═══ Difficulty Level Editor ═══ */}
            <div className="mb-4 border border-orange-200 dark:border-orange-700/50 rounded-xl overflow-hidden">
                <button onClick={() => setDifficultyEditorOpen(!difficultyEditorOpen)}
                    className={cn("w-full flex items-center justify-between px-4 py-2.5 text-sm font-semibold transition-colors",
                        difficultyEditorOpen ? "bg-orange-100 dark:bg-orange-900/40 text-orange-700 dark:text-orange-300"
                            : "bg-white/60 dark:bg-black/20 text-zinc-600 dark:text-zinc-400 hover:bg-orange-50 dark:hover:bg-orange-900/20"
                    )}>
                    <div className="flex items-center gap-2">
                        📊 Zorluk Seviyesi Tanımları
                        {isDifficultyModified && <span className="text-xs px-2 py-0.5 bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300 rounded-full">Değiştirildi</span>}
                    </div>
                    {difficultyEditorOpen ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                </button>
                {difficultyEditorOpen && (
                    <div className="p-4 space-y-3 bg-white/40 dark:bg-black/10">
                        {/* Toolbar */}
                        <div className="flex flex-wrap gap-2 mb-2">
                            {/* Favorites Dropdown */}
                            <div className="relative">
                                <button onClick={() => setDiffFavoritesOpen(!diffFavoritesOpen)}
                                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-300 rounded-lg hover:bg-amber-100 dark:hover:bg-amber-900/30 transition-colors border border-amber-200 dark:border-amber-800">
                                    <Star className="w-3.5 h-3.5" /> Favoriler ({difficultyFavorites.length}) <ChevronDown className="w-3 h-3" />
                                </button>
                                {diffFavoritesOpen && (
                                    <div className="absolute top-full left-0 mt-1 w-64 bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg shadow-xl z-50 max-h-60 overflow-y-auto">
                                        {difficultyFavorites.length === 0 ? (
                                            <div className="p-3 text-xs text-zinc-400 text-center italic">Henüz favori yok</div>
                                        ) : difficultyFavorites.map((fav) => (
                                            <div key={fav.id} className={cn("w-full flex items-center justify-between px-3 py-2 border-b border-zinc-100 dark:border-zinc-700 last:border-b-0 hover:bg-zinc-50 dark:hover:bg-zinc-700 transition-colors", fav.is_default ? "bg-amber-50/50 dark:bg-amber-900/10" : "")}>
                                                <button onClick={() => loadDifficultyFavorite(fav)} className="flex-1 min-w-0 text-left">
                                                    <div className="flex items-center gap-2">
                                                        <div className="font-medium truncate">{fav.name}</div>
                                                        {fav.is_default && <span className="text-[10px] px-1.5 py-0.5 bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300 rounded-full font-bold">Varsayılan</span>}
                                                    </div>
                                                    <div className="text-xs text-zinc-400">{new Date(fav.created_at).toLocaleDateString("tr-TR")}</div>
                                                </button>
                                                <div className="flex items-center gap-1">
                                                    <button onClick={(e) => toggleDefaultDifficultyFavorite(fav, e)}
                                                        className={cn("p-1.5 rounded shrink-0 transition-colors", fav.is_default ? "text-amber-500 hover:text-amber-600 bg-amber-100 dark:bg-amber-900/30" : "text-zinc-300 hover:text-amber-400 hover:bg-zinc-100 dark:hover:bg-zinc-600")}
                                                        title={fav.is_default ? "Varsayılanı kaldır" : "Varsayılan yap"}>
                                                        <Star className={cn("w-3.5 h-3.5", fav.is_default && "fill-current")} />
                                                    </button>
                                                    <button onClick={(e) => deleteDifficultyFavorite(fav.id, e)} className="p-1.5 text-red-400 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 rounded shrink-0" title="Sil">
                                                        <Trash2 className="w-3.5 h-3.5" />
                                                    </button>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>

                            {/* Save */}
                            {showDiffSaveInput ? (
                                <div className="flex items-center gap-1">
                                    <input type="text" value={diffSaveName} onChange={(e) => setDiffSaveName(e.target.value)} placeholder="Şablon adı..."
                                        className="px-2 py-1 text-xs border border-zinc-300 dark:border-zinc-600 rounded-lg bg-white dark:bg-zinc-800 w-32 focus:outline-none focus:ring-1 focus:ring-orange-500"
                                        onKeyDown={(e) => e.key === "Enter" && saveDifficultyFavorite()} autoFocus />
                                    <button onClick={saveDifficultyFavorite} disabled={!diffSaveName.trim()} className="p-1.5 text-green-600 hover:bg-green-50 rounded-lg disabled:opacity-40"><Save className="w-3.5 h-3.5" /></button>
                                    <button onClick={() => { setShowDiffSaveInput(false); setDiffSaveName("") }} className="p-1.5 text-zinc-400 hover:bg-zinc-100 rounded-lg"><X className="w-3.5 h-3.5" /></button>
                                </div>
                            ) : (
                                <button onClick={() => setShowDiffSaveInput(true)}
                                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-300 rounded-lg hover:bg-green-100 border border-green-200 dark:border-green-800">
                                    <Save className="w-3.5 h-3.5" /> Kaydet
                                </button>
                            )}

                            {/* Reset */}
                            <button onClick={resetDifficultyToDefault} disabled={!isDifficultyModified}
                                className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium text-zinc-500 hover:text-zinc-700 disabled:opacity-40 bg-zinc-100 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg">
                                <RotateCcw className="w-3 h-3" /> Varsayılana Dön
                            </button>
                        </div>

                        {["1", "2", "3", "4"].map(level => (
                            <div key={level} className="space-y-1">
                                <label className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">
                                    {DIFFICULTY_LABELS[level]} (Seviye {level})
                                </label>
                                <textarea
                                    value={customDifficultyLevels[level] || ""}
                                    onChange={(e) => setCustomDifficultyLevels(prev => ({ ...prev, [level]: e.target.value }))}
                                    rows={2}
                                    className="w-full text-xs font-mono leading-relaxed p-2 bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg resize-y focus:outline-none focus:ring-1 focus:ring-orange-500"
                                />
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {/* ═══ Prompt Editor Section ═══ */}
            <div className="mb-6 border border-purple-200 dark:border-purple-700/50 rounded-xl overflow-hidden">
                <button onClick={() => setPromptEditorOpen(!promptEditorOpen)}
                    className={cn("w-full flex items-center justify-between px-4 py-3 text-sm font-semibold transition-colors",
                        promptEditorOpen ? "bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-300"
                            : "bg-white/60 dark:bg-black/20 text-zinc-600 dark:text-zinc-400 hover:bg-purple-50 dark:hover:bg-purple-900/20"
                    )}>
                    <div className="flex items-center gap-2">
                        ✏️ Prompt Düzenle
                        {isModified && <span className="text-xs px-2 py-0.5 bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300 rounded-full">Değiştirildi</span>}
                    </div>
                    {promptEditorOpen ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                </button>

                {promptEditorOpen && (
                    <div className="p-4 space-y-4 bg-white/40 dark:bg-black/10">
                        {/* Toolbar */}
                        <div className="flex flex-wrap gap-2">
                            {/* Favorites Dropdown */}
                            <div className="relative">
                                <button onClick={() => setFavoritesOpen(!favoritesOpen)}
                                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-300 rounded-lg hover:bg-amber-100 dark:hover:bg-amber-900/30 transition-colors border border-amber-200 dark:border-amber-800">
                                    <Star className="w-3.5 h-3.5" /> Favoriler ({favorites.length}) <ChevronDown className="w-3 h-3" />
                                </button>
                                {favoritesOpen && (
                                    <div className="absolute top-full left-0 mt-1 w-64 bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg shadow-xl z-50 max-h-60 overflow-y-auto">
                                        {favorites.length === 0 ? (
                                            <div className="p-3 text-xs text-zinc-400 text-center italic">Henüz favori prompt yok</div>
                                        ) : favorites.map((fav) => (
                                            <div key={fav.id} className={cn("w-full flex items-center justify-between px-3 py-2 border-b border-zinc-100 dark:border-zinc-700 last:border-b-0 hover:bg-zinc-50 dark:hover:bg-zinc-700 transition-colors", fav.is_default ? "bg-amber-50/50 dark:bg-amber-900/10" : "")}>
                                                <button onClick={() => loadFavorite(fav)} className="flex-1 min-w-0 text-left">
                                                    <div className="flex items-center gap-2">
                                                        <div className="font-medium truncate">{fav.name}</div>
                                                        {fav.is_default && <span className="text-[10px] px-1.5 py-0.5 bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300 rounded-full font-bold">Varsayılan</span>}
                                                    </div>
                                                    <div className="text-xs text-zinc-400">{new Date(fav.created_at).toLocaleDateString("tr-TR")}</div>
                                                </button>
                                                <div className="flex items-center gap-1">
                                                    <button onClick={(e) => toggleDefaultFavorite(fav, e)}
                                                        className={cn("p-1.5 rounded shrink-0 transition-colors", fav.is_default ? "text-amber-500 hover:text-amber-600 bg-amber-100 dark:bg-amber-900/30" : "text-zinc-300 hover:text-amber-400 hover:bg-zinc-100 dark:hover:bg-zinc-600")}
                                                        title={fav.is_default ? "Varsayılanı kaldır" : "Varsayılan yap"}>
                                                        <Star className={cn("w-3.5 h-3.5", fav.is_default && "fill-current")} />
                                                    </button>
                                                    <button onClick={(e) => deleteFavorite(fav.id, e)} className="p-1.5 text-red-400 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 rounded shrink-0" title="Sil">
                                                        <Trash2 className="w-3.5 h-3.5" />
                                                    </button>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>

                            {/* Save */}
                            {showSaveInput ? (
                                <div className="flex items-center gap-1">
                                    <input type="text" value={saveName} onChange={(e) => setSaveName(e.target.value)} placeholder="Favori adı..."
                                        className="px-2 py-1 text-xs border border-zinc-300 dark:border-zinc-600 rounded-lg bg-white dark:bg-zinc-800 w-36 focus:outline-none focus:ring-1 focus:ring-purple-500"
                                        onKeyDown={(e) => e.key === "Enter" && saveFavorite()} autoFocus />
                                    <button onClick={saveFavorite} disabled={!saveName.trim()} className="p-1.5 text-green-600 hover:bg-green-50 rounded-lg disabled:opacity-40"><Save className="w-3.5 h-3.5" /></button>
                                    <button onClick={() => { setShowSaveInput(false); setSaveName("") }} className="p-1.5 text-zinc-400 hover:bg-zinc-100 rounded-lg"><X className="w-3.5 h-3.5" /></button>
                                </div>
                            ) : (
                                <button onClick={() => setShowSaveInput(true)}
                                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-300 rounded-lg hover:bg-green-100 border border-green-200 dark:border-green-800">
                                    <Save className="w-3.5 h-3.5" /> Tümünü Kaydet
                                </button>
                            )}

                            {/* Reset */}
                            <button onClick={resetToDefault} disabled={!isModified}
                                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 rounded-lg hover:bg-zinc-200 disabled:opacity-40 border border-zinc-200 dark:border-zinc-700">
                                <RotateCcw className="w-3.5 h-3.5" /> Varsayılana Dön
                            </button>

                            {/* Add Section */}
                            <button onClick={() => setShowAddSection(!showAddSection)}
                                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300 rounded-lg hover:bg-blue-100 border border-blue-200 dark:border-blue-800">
                                <PlusCircle className="w-3.5 h-3.5" /> Bölüm Ekle
                            </button>

                            {/* Var Reference */}
                            <div className="relative ml-auto">
                                <button onClick={() => setShowVarRef(!showVarRef)}
                                    className={cn("p-1.5 rounded-lg transition-colors border",
                                        showVarRef ? "bg-blue-50 text-blue-600 border-blue-200" : "bg-zinc-100 text-zinc-500 border-zinc-200 hover:bg-zinc-200"
                                    )} title="Değişken Referansı"><Info className="w-3.5 h-3.5" /></button>
                                {showVarRef && (
                                    <div className="absolute top-full right-0 mt-1 w-72 bg-white dark:bg-zinc-800 border rounded-lg shadow-xl z-50 p-3">
                                        <div className="text-xs font-semibold text-zinc-500 mb-2">Kullanılabilir Değişkenler</div>
                                        <div className="space-y-1.5">
                                            {TEMPLATE_VARS.map(v => (
                                                <div key={v.var} className="flex items-start gap-2 text-xs">
                                                    <code className="px-1.5 py-0.5 bg-purple-50 text-purple-600 rounded font-mono shrink-0">{v.var}</code>
                                                    <span className="text-zinc-500">{v.desc}</span>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}
                            </div>
                        </div>

                        {/* Add Section Input */}
                        {showAddSection && (
                            <div className="flex items-center gap-2 p-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg border border-blue-200 dark:border-blue-800">
                                <input type="text" value={newSectionLabel} onChange={(e) => { setNewSectionLabel(e.target.value); setNewSectionKey(e.target.value) }}
                                    placeholder="Bölüm adı (ör: Ek Kurallar)"
                                    className="flex-1 px-2 py-1.5 text-xs border border-zinc-300 dark:border-zinc-600 rounded-lg bg-white dark:bg-zinc-800 focus:outline-none focus:ring-1 focus:ring-blue-500"
                                    onKeyDown={(e) => e.key === "Enter" && addCustomSection()} autoFocus />
                                <button onClick={addCustomSection} disabled={!newSectionLabel.trim()}
                                    className="px-3 py-1.5 text-xs font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-40">Ekle</button>
                                <button onClick={() => { setShowAddSection(false); setNewSectionKey(""); setNewSectionLabel("") }}
                                    className="p-1.5 text-zinc-400 hover:bg-zinc-100 rounded-lg"><X className="w-3.5 h-3.5" /></button>
                            </div>
                        )}

                        {/* Modular Sections */}
                        <div className="space-y-3">
                            {sectionOrder.map((key) => {
                                const value = customSections[key] || ""
                                const isEnabled = enabledSections[key] ?? true
                                const isDefault = defaultSectionOrder.includes(key)
                                const isChanged = defaultSections ? value !== (defaultSections[key] ?? "") : false
                                const favs = sectionFavorites[key] || []

                                return (
                                    <div key={key} className={cn("rounded-lg border transition-colors",
                                        isEnabled ? "border-purple-200 dark:border-purple-700/50 bg-white/60 dark:bg-black/20"
                                            : "border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-900/30 opacity-50"
                                    )}>
                                        <div className="flex items-center justify-between px-3 py-2">
                                            <div className="flex items-center gap-2">
                                                <GripVertical className="w-3.5 h-3.5 text-zinc-300" />
                                                <button onClick={() => toggleSection(key)}
                                                    className={cn("relative w-8 h-4 rounded-full transition-colors", isEnabled ? "bg-purple-500" : "bg-zinc-300 dark:bg-zinc-600")}>
                                                    <div className={cn("absolute top-0.5 w-3 h-3 rounded-full bg-white shadow transition-transform", isEnabled ? "translate-x-4" : "translate-x-0.5")} />
                                                </button>
                                                <span className="text-sm font-medium">{getSectionLabel(key)}</span>
                                                {isChanged && <span className="w-1.5 h-1.5 rounded-full bg-amber-500" title="Değiştirildi" />}
                                                {!isDefault && (
                                                    <button onClick={() => removeSection(key)} className="p-0.5 text-red-400 hover:text-red-600 rounded" title="Bölümü Sil">
                                                        <Trash2 className="w-3 h-3" />
                                                    </button>
                                                )}
                                            </div>
                                            <div className="flex items-center gap-2">
                                                <span className="text-xs text-zinc-400 hidden sm:inline">{getSectionDescription(key)}</span>
                                                {/* Per-section favorites dropdown */}
                                                <div className="relative">
                                                    <button onClick={() => setSectionFavOpen(prev => ({ ...prev, [key]: !prev[key] }))}
                                                        className={cn("p-1 rounded transition-colors", favs.length > 0 ? "text-amber-500 hover:bg-amber-50" : "text-zinc-300 hover:bg-zinc-100")}
                                                        title={`Bu bölümün favorileri (${favs.length})`}>
                                                        <Star className="w-3.5 h-3.5" />
                                                    </button>
                                                    {sectionFavOpen[key] && (
                                                        <div className="absolute top-full right-0 mt-1 w-56 bg-white dark:bg-zinc-800 border rounded-lg shadow-xl z-50 overflow-hidden">
                                                            <div className="px-3 py-2 bg-zinc-50 dark:bg-zinc-900 border-b text-xs font-semibold text-zinc-500 flex items-center justify-between">
                                                                <span>{getSectionLabel(key)} Favorileri</span>
                                                                <button onClick={() => setSectionShowSave(prev => ({ ...prev, [key]: !prev[key] }))}
                                                                    className="text-green-600 hover:text-green-700"><Save className="w-3 h-3" /></button>
                                                            </div>
                                                            {sectionShowSave[key] && (
                                                                <div className="flex items-center gap-1 px-2 py-1.5 border-b">
                                                                    <input type="text" value={sectionSaveName[key] || ""} onChange={(e) => setSectionSaveName(prev => ({ ...prev, [key]: e.target.value }))}
                                                                        placeholder="Favori adı..." className="flex-1 px-1.5 py-0.5 text-xs border rounded bg-white dark:bg-zinc-800 focus:outline-none"
                                                                        onKeyDown={(e) => e.key === "Enter" && saveSectionFavorite(key)} autoFocus />
                                                                    <button onClick={() => saveSectionFavorite(key)} disabled={!sectionSaveName[key]?.trim()}
                                                                        className="p-1 text-green-600 disabled:opacity-40"><Save className="w-3 h-3" /></button>
                                                                </div>
                                                            )}
                                                            <div className="max-h-40 overflow-y-auto">
                                                                {favs.length === 0 ? (
                                                                    <div className="p-3 text-xs text-zinc-400 italic text-center">Favori yok</div>
                                                                ) : favs.map(fav => (
                                                                    <div key={fav.id} className="w-full flex items-center justify-between px-3 py-1.5 border-b last:border-b-0 hover:bg-zinc-50 dark:hover:bg-zinc-700 transition-colors">
                                                                        <button onClick={() => loadSectionFavorite(key, fav)} className="flex-1 min-w-0 text-left text-xs">
                                                                            <span className="truncate font-medium">{fav.name}</span>
                                                                        </button>
                                                                        <button onClick={(e) => deleteSectionFavorite(fav.id, e)} className="ml-1 p-0.5 text-red-400 hover:text-red-600 shrink-0">
                                                                            <Trash2 className="w-3 h-3" />
                                                                        </button>
                                                                    </div>
                                                                ))}
                                                            </div>
                                                        </div>
                                                    )}
                                                </div>
                                            </div>
                                        </div>
                                        {isEnabled && (
                                            <div className="px-3 pb-3">
                                                <textarea value={value} onChange={(e) => handleSectionChange(key, e.target.value)}
                                                    rows={key === "format_rules" || key === "example" ? 8 : key === "principles" ? 5 : 2}
                                                    className="w-full text-xs font-mono leading-relaxed p-2 bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg resize-y focus:outline-none focus:ring-1 focus:ring-purple-500"
                                                    placeholder={`${getSectionLabel(key)} bölümü...`} />
                                            </div>
                                        )}
                                    </div>
                                )
                            })}
                        </div>
                    </div>
                )}
            </div>

            {/* Action Buttons */}
            <div className="flex gap-3">
                <button onClick={onClear} disabled={selectedPdfs.length === 0 || isGenerating}
                    className="px-4 py-2 bg-zinc-200 dark:bg-zinc-700 rounded-lg text-sm font-medium hover:bg-zinc-300 dark:hover:bg-zinc-600 disabled:opacity-50 disabled:cursor-not-allowed">
                    Temizle
                </button>
                <button onClick={handleGenerate} disabled={selectedPdfs.length === 0 || isGenerating}
                    className={cn("flex-1 py-3 rounded-lg text-white font-bold flex items-center justify-center gap-2 transition-all",
                        isGenerating ? "bg-purple-400 cursor-wait" : "bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-700 hover:to-indigo-700",
                        selectedPdfs.length === 0 && "opacity-50 cursor-not-allowed"
                    )}>
                    {isGenerating ? (
                        <><Loader className="w-5 h-5 animate-spin" /> Üretiliyor...</>
                    ) : (
                        <>
                            <Sparkles className="w-5 h-5" />
                            {multiplier > 1
                                ? <span>{multiplier} Paket ({multiplier * questionCount} Soru) Başlat</span>
                                : <span>{questionCount} Soru Üret</span>}
                            {(isModified || isDifficultyModified) && <span className="text-xs opacity-75">(Özel Prompt)</span>}
                        </>
                    )}
                </button>
            </div>
        </div>
    )
}
