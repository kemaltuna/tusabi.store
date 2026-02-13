"use client"

import { useQuery, useQueryClient } from "@tanstack/react-query"
import { fetchNextCard } from "../lib/api"
import { QuizCard } from "../components/QuizCard"
import { useState, useEffect } from "react"
import { useRouter } from "next/navigation"
import { RefreshCw, LogOut, User } from "lucide-react"
import { useAuth } from "../lib/auth"

export default function Home() {
  const queryClient = useQueryClient()
  const [topic, setTopic] = useState<string | undefined>(undefined)
  const { user, logout, isLoading: authLoading } = useAuth()
  const router = useRouter()

  // Redirect to login if not authenticated, to dashboard if authenticated
  useEffect(() => {
    if (!authLoading) {
      if (!user) {
        router.push("/login")
      } else {
        // Authenticated users go to dashboard
        router.push("/dashboard")
      }
    }
  }, [authLoading, user, router])

  const { data: card, isLoading, isError, refetch } = useQuery({
    queryKey: ["next-card", topic],
    queryFn: () => fetchNextCard("standard", topic),
    refetchOnWindowFocus: false,
    enabled: !!user, // Only fetch if authenticated
  })

  const handleNext = () => {
    // Invalidate to fetch new card
    queryClient.invalidateQueries({ queryKey: ["next-card"] })
  }

  const handleLogout = () => {
    logout()
    router.push("/login")
  }

  // Show loading while checking auth
  if (authLoading) {
    return (
      <div className="min-h-screen bg-zinc-50 dark:bg-black flex items-center justify-center">
        <RefreshCw className="w-8 h-8 animate-spin text-blue-500" />
      </div>
    )
  }

  // Don't render if not authenticated (will redirect)
  if (!user) return null

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-black text-zinc-900 dark:text-zinc-100 p-4 md:p-8 font-[family-name:var(--font-geist-sans)]">
      <header className="max-w-4xl mx-auto mb-8 flex justify-between items-center">
        <h1 className="text-2xl font-bold tracking-tight">MedQuiz Pro <span className="text-blue-500 text-sm align-top">v2</span></h1>

        <div className="flex items-center gap-4">
          <select
            className="bg-transparent border border-zinc-300 dark:border-zinc-700 rounded px-2 py-1 text-sm"
            value={topic || ""}
            onChange={(e) => setTopic(e.target.value || undefined)}
          >
            <option value="">Tüm Konular</option>
            <option value="Patoloji">Patoloji</option>
            <option value="Dahiliye">Dahiliye</option>
            {/* We should fetch topics dynamically later */}
          </select>

          {/* User Info */}
          <div className="flex items-center gap-2 text-sm text-zinc-500 dark:text-zinc-400">
            <User className="w-4 h-4" />
            <span>{user.username}</span>
            {user.role === "admin" && (
              <span className="bg-purple-500/20 text-purple-400 px-2 py-0.5 rounded text-xs">Admin</span>
            )}
          </div>

          {/* Logout Button */}
          <button
            onClick={handleLogout}
            className="p-2 text-zinc-500 hover:text-red-500 transition-colors"
            title="Çıkış Yap"
          >
            <LogOut className="w-5 h-5" />
          </button>
        </div>
      </header>

      <main className="flex flex-col items-center">
        {isLoading ? (
          <div className="flex flex-col items-center justify-center py-20 animate-pulse text-zinc-400">
            <RefreshCw className="w-8 h-8 animate-spin mb-4" />
            <p>Yükleniyor...</p>
          </div>
        ) : isError ? (
          <div className="p-4 bg-red-50 text-red-600 rounded-lg">
            Hata oluştu. Backend çalışıyor mu? (Port 8000)
            <button onClick={() => refetch()} className="ml-4 underline">Tekrar Dene</button>
          </div>
        ) : !card ? (
          <div className="text-center py-20">
            <h2 className="text-xl font-semibold mb-2">🎉 Hepsini Bitirdin!</h2>
            <p className="text-zinc-500">Şu an için tekrar edilecek kart yok.</p>
            <button onClick={() => refetch()} className="mt-4 px-4 py-2 bg-zinc-200 dark:bg-zinc-800 rounded">
              Yenile
            </button>
          </div>
        ) : (
          <QuizCard card={card} onNext={handleNext} />
        )}
      </main>
    </div>
  );
}
