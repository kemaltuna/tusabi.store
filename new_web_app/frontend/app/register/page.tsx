"use client"

import { useState } from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { useAuth } from "../../lib/auth"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "/api"

export default function RegisterPage() {
    const [username, setUsername] = useState("")
    const [password, setPassword] = useState("")
    const [confirmPassword, setConfirmPassword] = useState("")
    const [error, setError] = useState("")
    const [isLoading, setIsLoading] = useState(false)
    const { login } = useAuth()
    const router = useRouter()

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault()
        setError("")

        if (password !== confirmPassword) {
            setError("Şifreler eşleşmiyor")
            return
        }

        setIsLoading(true)

        try {
            const res = await fetch(`${API_BASE}/auth/register`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ username, password })
            })

            if (!res.ok) {
                let message = "Kayıt başarısız"
                try {
                    const data = await res.json()
                    if (data?.detail) {
                        message = data.detail
                    }
                } catch {
                    // Keep default message on parse error
                }
                if (message === "Username already exists") {
                    message = "Bu kullanıcı adı zaten kullanılıyor"
                }
                setError(message)
                return
            }

            const loginSuccess = await login(username, password)
            if (loginSuccess) {
                router.push("/")
            } else {
                setError("Kayıt başarılı ama giriş yapılamadı. Lütfen tekrar deneyin.")
            }
        } catch (err) {
            console.error("Register failed:", err)
            setError("Kayıt sırasında hata oluştu")
        } finally {
            setIsLoading(false)
        }
    }

    return (
        <div className="min-h-screen bg-gradient-to-br from-blue-900 via-purple-900 to-indigo-900 flex items-center justify-center p-4">
            <div className="w-full max-w-md">
                {/* Logo/Title */}
                <div className="text-center mb-8">
                    <h1 className="text-4xl font-bold text-white tracking-tight">
                        🧬 TUSabi
                    </h1>
                    <p className="text-blue-200 mt-2">Tıp Eğitiminin Geleceği</p>
                </div>

                {/* Register Card */}
                <div className="bg-white/10 backdrop-blur-lg rounded-2xl p-8 shadow-2xl border border-white/20">
                    <h2 className="text-2xl font-semibold text-white mb-6 text-center">
                        Kayıt Ol
                    </h2>

                    <form onSubmit={handleSubmit} className="space-y-5">
                        <div>
                            <label className="block text-sm font-medium text-blue-100 mb-2">
                                Kullanıcı Adı
                            </label>
                            <input
                                type="text"
                                value={username}
                                onChange={(e) => setUsername(e.target.value)}
                                className="w-full px-4 py-3 bg-white/10 border border-white/20 rounded-lg text-white placeholder-blue-200/50 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-transparent transition-all"
                                placeholder="Kullanıcı adınızı girin"
                                autoComplete="username"
                                required
                            />
                        </div>

                        <div>
                            <label className="block text-sm font-medium text-blue-100 mb-2">
                                Şifre
                            </label>
                            <input
                                type="password"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                className="w-full px-4 py-3 bg-white/10 border border-white/20 rounded-lg text-white placeholder-blue-200/50 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-transparent transition-all"
                                placeholder="Şifrenizi girin"
                                autoComplete="new-password"
                                required
                            />
                        </div>

                        <div>
                            <label className="block text-sm font-medium text-blue-100 mb-2">
                                Şifre Tekrar
                            </label>
                            <input
                                type="password"
                                value={confirmPassword}
                                onChange={(e) => setConfirmPassword(e.target.value)}
                                className="w-full px-4 py-3 bg-white/10 border border-white/20 rounded-lg text-white placeholder-blue-200/50 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-transparent transition-all"
                                placeholder="Şifrenizi tekrar girin"
                                autoComplete="new-password"
                                required
                            />
                        </div>

                        {error && (
                            <div className="bg-red-500/20 border border-red-500/50 rounded-lg p-3 text-red-200 text-sm text-center">
                                {error}
                            </div>
                        )}

                        <button
                            type="submit"
                            disabled={isLoading}
                            className="w-full py-3 bg-gradient-to-r from-blue-500 to-purple-600 text-white font-semibold rounded-lg hover:from-blue-600 hover:to-purple-700 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:ring-offset-2 focus:ring-offset-transparent transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            {isLoading ? "Kayıt oluşturuluyor..." : "Kayıt Ol"}
                        </button>
                    </form>

                    <p className="text-center text-blue-100/80 text-sm mt-6">
                        Zaten hesabın var mı?{" "}
                        <Link href="/login" className="text-white hover:text-blue-200 underline underline-offset-4">
                            Giriş Yap
                        </Link>
                    </p>
                </div>

                {/* Footer */}
                <p className="text-center text-blue-200/60 text-sm mt-6">
                    TUSabi v2 • Microservices Architecture
                </p>
            </div>
        </div>
    )
}
