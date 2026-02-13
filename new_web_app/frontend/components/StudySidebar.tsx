"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { Bell, BellOff, Pause, Play, RotateCcw, Timer, CheckCircle2, Coffee, Square } from "lucide-react"
import { cn } from "../lib/utils"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "/api"

type StudyMode = "study" | "break"

interface SessionRecord {
    id: string
    subject: string
    type: StudyMode
    minutes: number
    startedAt: string
    endedAt: string
}

const SETTINGS_KEY = "medquiz_study_settings_v1"
const SESSIONS_KEY = "medquiz_study_sessions_v1"


const DEFAULT_SETTINGS = {
    studyMinutes: 50,
    breakMinutes: 10,
    subject: "",
    autoSwitch: true
}

const DEFAULT_READING_MODE = false

const clampMinutes = (value: number, min: number, max: number) => {
    if (Number.isNaN(value)) return min
    return Math.min(max, Math.max(min, value))
}

const formatTime = (totalSeconds: number) => {
    const minutes = Math.floor(totalSeconds / 60)
    const seconds = Math.floor(totalSeconds % 60)
    return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`
}

const formatShortTime = (iso: string) => {
    const date = new Date(iso)
    return date.toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" })
}

const createId = () => {
    if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
        return crypto.randomUUID()
    }
    return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function StudySidebar() {
    const [studyMinutes, setStudyMinutes] = useState(DEFAULT_SETTINGS.studyMinutes)
    const [breakMinutes, setBreakMinutes] = useState(DEFAULT_SETTINGS.breakMinutes)
    const [subject, setSubject] = useState(DEFAULT_SETTINGS.subject)
    const [autoSwitch, setAutoSwitch] = useState(DEFAULT_SETTINGS.autoSwitch)
    const [readingMode, setReadingMode] = useState(DEFAULT_READING_MODE)

    const [mode, setMode] = useState<StudyMode>("study")
    const [remainingSeconds, setRemainingSeconds] = useState(DEFAULT_SETTINGS.studyMinutes * 60)
    const [isRunning, setIsRunning] = useState(false)

    const [sessions, setSessions] = useState<SessionRecord[]>([])
    const [subjectOptions, setSubjectOptions] = useState<string[]>([])
    const [notificationPermission, setNotificationPermission] = useState<NotificationPermission>("default")

    const elapsedSecondsRef = useRef(0)
    const lastTickRef = useRef<number | null>(null)
    const sessionStartRef = useRef<number | null>(null)
    const completionLockRef = useRef(false)
    const settingsRef = useRef({ mode: "study" as StudyMode, plannedSeconds: 0 })

    const plannedSeconds = (mode === "study" ? studyMinutes : breakMinutes) * 60

    useEffect(() => {
        if (typeof window === "undefined") return

        try {
            const saved = localStorage.getItem(SETTINGS_KEY)
            if (saved) {
                const parsed = JSON.parse(saved)
                setStudyMinutes(clampMinutes(parsed.studyMinutes ?? DEFAULT_SETTINGS.studyMinutes, 15, 120))
                setBreakMinutes(clampMinutes(parsed.breakMinutes ?? DEFAULT_SETTINGS.breakMinutes, 5, 60))
                setSubject(typeof parsed.subject === "string" ? parsed.subject : "")
                setAutoSwitch(parsed.autoSwitch ?? DEFAULT_SETTINGS.autoSwitch)
            }
        } catch (error) {
            console.warn("Failed to load study settings", error)
        }

        try {
            const savedReadingMode = localStorage.getItem("medquiz_reading_mode_v1")
            if (savedReadingMode) {
                setReadingMode(JSON.parse(savedReadingMode))
            }
        } catch (error) {
            console.warn("Failed to load reading mode settings", error)
        }

        try {
            const savedSessions = localStorage.getItem(SESSIONS_KEY)
            if (savedSessions) {
                const parsedSessions = JSON.parse(savedSessions)
                if (Array.isArray(parsedSessions)) {
                    setSessions(parsedSessions)
                }
            }
        } catch (error) {
            console.warn("Failed to load study sessions", error)
        }

        if ("Notification" in window) {
            setNotificationPermission(Notification.permission)
        }
    }, [])

    useEffect(() => {
        if (typeof window === "undefined") return
        localStorage.setItem(
            SETTINGS_KEY,
            JSON.stringify({ studyMinutes, breakMinutes, subject, autoSwitch })
        )
    }, [studyMinutes, breakMinutes, subject, autoSwitch])

    useEffect(() => {
        if (typeof window === "undefined") return
        localStorage.setItem("medquiz_reading_mode_v1", JSON.stringify(readingMode))
    }, [readingMode])

    useEffect(() => {
        if (typeof window === "undefined") return
        localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions))
    }, [sessions])

    useEffect(() => {
        let active = true
        const fetchSubjects = async () => {
            try {
                const res = await fetch(`${API_BASE}/library/tree`)
                if (!res.ok) return
                const data = await res.json()
                if (!active || !data) return
                setSubjectOptions(Object.keys(data))
            } catch (error) {
                console.warn("Failed to load subjects", error)
            }
        }
        fetchSubjects()
        return () => {
            active = false
        }
    }, [])

    useEffect(() => {
        if (!isRunning) return

        const interval = window.setInterval(() => {
            const now = Date.now()
            if (lastTickRef.current === null) {
                lastTickRef.current = now
                return
            }
            const deltaSeconds = Math.max(1, Math.floor((now - lastTickRef.current) / 1000))
            lastTickRef.current = now

            elapsedSecondsRef.current += deltaSeconds

            setRemainingSeconds(prev => {
                const next = Math.max(0, prev - deltaSeconds)
                if (next === 0 && !completionLockRef.current) {
                    completionLockRef.current = true
                    completeSession(true)
                }
                return next
            })
        }, 1000)

        return () => window.clearInterval(interval)
    }, [isRunning])

    useEffect(() => {
        const prev = settingsRef.current
        const settingsChanged = prev.mode !== mode || prev.plannedSeconds !== plannedSeconds
        settingsRef.current = { mode, plannedSeconds }

        if (!settingsChanged || isRunning) return

        setRemainingSeconds(plannedSeconds)
        elapsedSecondsRef.current = 0
        lastTickRef.current = null
        sessionStartRef.current = null
        completionLockRef.current = false
    }, [mode, plannedSeconds, isRunning])

    useEffect(() => {
        if (typeof document === "undefined") return

        if (readingMode) {
            document.documentElement.classList.add("reading-mode")
            // Remove any legacy filter if it exists
            document.documentElement.style.removeProperty("--app-filter")
        } else {
            document.documentElement.classList.remove("reading-mode")
        }
    }, [readingMode])

    const notify = (title: string, body: string) => {
        if (typeof window === "undefined") return
        if (!("Notification" in window)) return
        if (Notification.permission !== "granted") return
        new Notification(title, { body })
    }

    const requestNotificationPermission = async () => {
        if (typeof window === "undefined") return
        if (!("Notification" in window)) return
        const result = await Notification.requestPermission()
        setNotificationPermission(result)
    }

    const getElapsedSeconds = () => {
        if (!isRunning || lastTickRef.current === null) return elapsedSecondsRef.current
        const deltaSeconds = Math.max(0, Math.floor((Date.now() - lastTickRef.current) / 1000))
        return elapsedSecondsRef.current + deltaSeconds
    }

    const completeSession = (finishedNaturally: boolean) => {
        completionLockRef.current = true
        const elapsedSeconds = finishedNaturally ? plannedSeconds : getElapsedSeconds()
        const elapsedMinutes = Math.max(1, Math.round(elapsedSeconds / 60))
        const loggedMinutes = finishedNaturally
            ? Math.max(1, Math.round(plannedSeconds / 60))
            : Math.min(Math.max(1, Math.round(plannedSeconds / 60)), elapsedMinutes)

        const startedAt = sessionStartRef.current
            ? new Date(sessionStartRef.current).toISOString()
            : new Date(Date.now() - elapsedSeconds * 1000).toISOString()

        const endedAt = new Date().toISOString()
        const safeSubject = subject.trim() || "Genel"

        const record: SessionRecord = {
            id: createId(),
            subject: safeSubject,
            type: mode,
            minutes: loggedMinutes,
            startedAt,
            endedAt
        }

        setSessions(prev => [record, ...prev].slice(0, 200))

        setIsRunning(false)
        lastTickRef.current = null
        elapsedSecondsRef.current = 0
        sessionStartRef.current = null

        notify(
            mode === "study" ? "Etut tamamlandı" : "Mola bitti",
            mode === "study"
                ? `${safeSubject} - ${loggedMinutes} dk`
                : `Mola tamamlandı (${loggedMinutes} dk)`
        )

        if (autoSwitch) {
            setMode(mode === "study" ? "break" : "study")
        } else {
            setRemainingSeconds(plannedSeconds)
        }
    }

    const handleMainButton = () => {
        if (!isRunning) {
            // Not running - Start whatever mode we are in
            completionLockRef.current = false
            if (!sessionStartRef.current) {
                sessionStartRef.current = Date.now()
            }
            lastTickRef.current = Date.now()
            setIsRunning(true)
        } else {
            // Running - The button acts as "Switch Mode"
            // If Study -> Complete Study & Start Break
            // If Break -> Complete Break & Start Study

            // First complete current session
            completeSession(false)

            // Then logic to switch and start next is needed. 
            // completeSession already handles 'autoSwitch' if true.
            // But we want to FORCE switch and START.

            // We need to wait for state update or force it here.
            // Since setState is async, we can't rely on `mode` changing immediately if we just called completeSession
            // safely, let's look at how completeSession works. It sets 'mode' if autoSwitch is on.
            // But it doesn't start it.

            // Let's change this: manual click on "Mola Ver" implies we want to start the break immediately.
            // The user said "press button to enter break".

            // Implementation:
            // 1. Calculate stats for current session (done in completeSession)
            // 2. Switch mode manually (reverse of current)
            // 3. Start timer immediately for the new mode.

            const nextMode = mode === "study" ? "break" : "study"
            setMode(nextMode)

            // Reset timer for next mode
            const nextPlanned = (nextMode === "study" ? studyMinutes : breakMinutes) * 60
            setRemainingSeconds(nextPlanned)
            elapsedSecondsRef.current = 0

            // Start immediately
            sessionStartRef.current = Date.now()
            lastTickRef.current = Date.now()
            setIsRunning(true)
            completionLockRef.current = false
        }
    }

    const handleFinishWork = () => {
        if (!isRunning && elapsedSecondsRef.current === 0) return

        completeSession(false)
        setIsRunning(false)
    }

    const stats = useMemo(() => {
        const now = new Date()
        const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
        const sevenDaysAgo = startOfToday - 6 * 24 * 60 * 60 * 1000

        const totals = {
            todayStudy: 0,
            todayBreak: 0,
            weekStudy: 0,
            weekBreak: 0
        }

        const subjectTotals = new Map<string, number>()
        const recentSessions = [...sessions]
            .sort((a, b) => Date.parse(b.endedAt) - Date.parse(a.endedAt))
            .slice(0, 6)

        sessions.forEach(session => {
            const endedAt = Date.parse(session.endedAt)
            if (Number.isNaN(endedAt)) return

            if (endedAt >= startOfToday) {
                if (session.type === "study") totals.todayStudy += session.minutes
                if (session.type === "break") totals.todayBreak += session.minutes
            }

            if (endedAt >= sevenDaysAgo) {
                if (session.type === "study") totals.weekStudy += session.minutes
                if (session.type === "break") totals.weekBreak += session.minutes
            }

            if (session.type === "study") {
                subjectTotals.set(session.subject, (subjectTotals.get(session.subject) || 0) + session.minutes)
            }
        })

        const topSubjects = [...subjectTotals.entries()]
            .sort((a, b) => b[1] - a[1])
            .slice(0, 3)

        return { totals, topSubjects, recentSessions }
    }, [sessions])

    const progress = plannedSeconds > 0 ? 1 - remainingSeconds / plannedSeconds : 0

    return (
        <div className="h-full flex flex-col gap-4 p-4">
            <div className="flex items-center justify-between">
                <div>
                    <p className="text-xs uppercase tracking-[0.3em] text-zinc-400">Etut Paneli</p>
                    <h2 className="text-lg font-semibold flex items-center gap-2">
                        <Timer className="w-5 h-5 text-blue-500" />
                        Calisma ve Mola
                    </h2>
                </div>
                <button
                    onClick={requestNotificationPermission}
                    className={cn(
                        "flex items-center gap-2 text-xs px-2 py-1 rounded-full border",
                        notificationPermission === "granted"
                            ? "border-emerald-300/60 text-emerald-600 dark:text-emerald-300"
                            : "border-zinc-200 dark:border-zinc-700 text-zinc-500"
                    )}
                    title="Bildirim izni"
                >
                    {notificationPermission === "granted" ? (
                        <Bell className="w-3.5 h-3.5" />
                    ) : (
                        <BellOff className="w-3.5 h-3.5" />
                    )}
                    Bildirim
                </button>
            </div>

            <div className="rounded-2xl border border-white/60 dark:border-zinc-700/40 bg-white/70 dark:bg-zinc-900/60 p-4 shadow-lg space-y-3">
                <div>
                    <p className="text-xs uppercase tracking-[0.3em] text-zinc-400">Gorunum</p>
                    <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-200">
                        Okuma Modu
                    </h3>
                </div>

                <div className="flex items-center justify-between gap-3">
                    <div>
                        <p className="text-xs text-zinc-700 dark:text-zinc-200">Kitap Gorunumu</p>
                        <p className="text-[11px] text-zinc-400">Goz yormayan, sicak renkli okuma deneyimi.</p>
                    </div>
                    <button
                        role="switch"
                        aria-checked={readingMode}
                        onClick={() => setReadingMode(!readingMode)}
                        className={cn(
                            "relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-amber-500 focus:ring-offset-2",
                            readingMode ? "bg-amber-500" : "bg-zinc-200 dark:bg-zinc-700"
                        )}
                    >
                        <span
                            aria-hidden="true"
                            className={cn(
                                "pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out",
                                readingMode ? "translate-x-5" : "translate-x-0"
                            )}
                        />
                    </button>
                </div>
            </div>

            <div className="rounded-2xl border border-white/60 dark:border-zinc-700/40 bg-white/70 dark:bg-zinc-900/60 p-4 shadow-lg">
                <div className="flex items-center justify-between">
                    <div className="flex gap-2">
                        {/* Removed manual tabs per user request for simplicity */}
                    </div>
                    <span className="text-xs font-medium text-zinc-500 bg-zinc-100 dark:bg-zinc-800 px-2 py-1 rounded-md">
                        {mode === "study" ? "Ders Zamani" : "Mola Zamani"}
                    </span>
                    <span className="text-xs text-zinc-400">
                        {mode === "study" ? "Odak" : "Dinlen"}
                    </span>
                </div>

                <div className="mt-4 flex items-end justify-between">
                    <div>
                        <p className="text-4xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">
                            {formatTime(remainingSeconds)}
                        </p>
                        <p className="text-xs text-zinc-500">
                            {mode === "study" ? "Etut" : "Mola"} suresi
                        </p>
                    </div>
                    <div className="flex flex-col gap-2 w-full sm:w-auto">
                        <button
                            onClick={handleMainButton}
                            className={cn(
                                "w-full sm:w-auto px-6 py-3 rounded-xl text-sm font-semibold text-white transition shadow-lg flex items-center gap-2 justify-center",
                                isRunning
                                    ? (mode === "study" ? "bg-amber-500 hover:bg-amber-600 shadow-amber-500/20" : "bg-blue-600 hover:bg-blue-700 shadow-blue-600/30")
                                    : "bg-emerald-600 hover:bg-emerald-700 shadow-emerald-600/30"
                            )}
                        >
                            {isRunning ? (
                                mode === "study" ? (
                                    <>
                                        <Coffee className="w-5 h-5" />
                                        Mola Ver
                                    </>
                                ) : (
                                    <>
                                        <Play className="w-5 h-5" />
                                        Derse Don
                                    </>
                                )
                            ) : (
                                <>
                                    <Play className="w-5 h-5" />
                                    {mode === "study" ? "Derse Basla" : "Molayi Baslat"}
                                </>
                            )}
                        </button>

                        <button
                            onClick={handleFinishWork}
                            className="w-full sm:w-auto px-4 py-2 rounded-xl border border-zinc-200 dark:border-zinc-700 text-zinc-500 dark:text-zinc-400 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition flex items-center justify-center gap-2 text-xs"
                            title="Calismayi tamamen bitir"
                        >
                            <Square className="w-3 h-3 fill-current" />
                            Gunu Bitir
                        </button>
                    </div>
                </div>

                <div className="mt-4">
                    <div className="h-2 rounded-full bg-zinc-200 dark:bg-zinc-800 overflow-hidden">
                        <div
                            className={cn(
                                "h-full transition-all",
                                mode === "study" ? "bg-blue-500" : "bg-emerald-500"
                            )}
                            style={{ width: `${Math.min(100, Math.max(0, progress * 100))}%` }}
                        />
                    </div>
                </div>

                <div className="mt-4 grid grid-cols-2 gap-3 text-xs">
                    <label className="flex flex-col gap-1 text-zinc-500">
                        Etut (dk)
                        <input
                            type="number"
                            min={15}
                            max={120}
                            value={studyMinutes}
                            disabled={isRunning}
                            onChange={(event) =>
                                setStudyMinutes(clampMinutes(Number(event.target.value), 15, 120))
                            }
                            className="w-full rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white/80 dark:bg-zinc-900/70 px-2 py-1 text-sm text-zinc-700 dark:text-zinc-100"
                        />
                    </label>
                    <label className="flex flex-col gap-1 text-zinc-500">
                        Mola (dk)
                        <input
                            type="number"
                            min={5}
                            max={60}
                            value={breakMinutes}
                            disabled={isRunning}
                            onChange={(event) =>
                                setBreakMinutes(clampMinutes(Number(event.target.value), 5, 60))
                            }
                            className="w-full rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white/80 dark:bg-zinc-900/70 px-2 py-1 text-sm text-zinc-700 dark:text-zinc-100"
                        />
                    </label>
                </div>

                <div className="mt-4 grid gap-3 text-xs">
                    <label className="flex flex-col gap-1 text-zinc-500">
                        Calisilan ders
                        <input
                            list="study-subjects"
                            value={subject}
                            onChange={(event) => setSubject(event.target.value)}
                            placeholder="Orn. Anatomi"
                            className="w-full rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white/80 dark:bg-zinc-900/70 px-2 py-1 text-sm text-zinc-700 dark:text-zinc-100"
                        />
                        <datalist id="study-subjects">
                            {subjectOptions.map(option => (
                                <option key={option} value={option} />
                            ))}
                        </datalist>
                    </label>
                    <label className="flex items-center gap-2 text-zinc-500">
                        <input
                            type="checkbox"
                            checked={autoSwitch}
                            onChange={(event) => setAutoSwitch(event.target.checked)}
                            className="accent-blue-500"
                        />
                        Otomatik donus (Etut/Mola)
                    </label>
                </div>
            </div>

            <div className="rounded-2xl border border-white/60 dark:border-zinc-700/40 bg-white/70 dark:bg-zinc-900/60 p-4 shadow-lg space-y-3">
                <div>
                    <p className="text-xs uppercase tracking-[0.3em] text-zinc-400">Istatistik</p>
                    <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-200">
                        Son aktiviteler
                    </h3>
                </div>

                <div className="grid grid-cols-2 gap-3 text-xs">
                    <div className="rounded-lg bg-white/80 dark:bg-zinc-900/80 border border-zinc-100 dark:border-zinc-700 p-2">
                        <p className="text-zinc-400">Bugun</p>
                        <p className="text-sm font-semibold text-zinc-800 dark:text-zinc-100">
                            {stats.totals.todayStudy} dk etut
                        </p>
                        <p className="text-zinc-400">{stats.totals.todayBreak} dk mola</p>
                    </div>
                    <div className="rounded-lg bg-white/80 dark:bg-zinc-900/80 border border-zinc-100 dark:border-zinc-700 p-2">
                        <p className="text-zinc-400">Son 7 gun</p>
                        <p className="text-sm font-semibold text-zinc-800 dark:text-zinc-100">
                            {stats.totals.weekStudy} dk etut
                        </p>
                        <p className="text-zinc-400">{stats.totals.weekBreak} dk mola</p>
                    </div>
                </div>

                <div className="space-y-2 text-xs">
                    <p className="text-zinc-400">En cok calisilan</p>
                    {stats.topSubjects.length === 0 ? (
                        <p className="text-zinc-500">Henuz veri yok.</p>
                    ) : (
                        stats.topSubjects.map(([name, minutes]) => (
                            <div key={name} className="flex items-center justify-between">
                                <span className="truncate text-zinc-600 dark:text-zinc-300">{name}</span>
                                <span className="text-zinc-400">{minutes} dk</span>
                            </div>
                        ))
                    )}
                </div>

                <div className="space-y-2 text-xs">
                    <p className="text-zinc-400">Son seanslar</p>
                    {stats.recentSessions.length === 0 ? (
                        <p className="text-zinc-500">Henuz kayit yok.</p>
                    ) : (
                        stats.recentSessions.map(session => (
                            <div
                                key={session.id}
                                className="flex items-center justify-between rounded-lg bg-white/70 dark:bg-zinc-900/80 border border-zinc-100 dark:border-zinc-800 px-2 py-1"
                            >
                                <div>
                                    <p className="text-zinc-700 dark:text-zinc-200">
                                        {session.subject}
                                        <span className="ml-2 text-[10px] text-zinc-400">
                                            {session.type === "study" ? "Etut" : "Mola"}
                                        </span>
                                    </p>
                                    <p className="text-[10px] text-zinc-400">{formatShortTime(session.endedAt)}</p>
                                </div>
                                <span className="text-zinc-500">{session.minutes} dk</span>
                            </div>
                        ))
                    )}
                </div>
            </div>
        </div>
    )
}
