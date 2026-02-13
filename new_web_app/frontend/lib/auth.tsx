"use client"

import { createContext, useContext, useState, useEffect, ReactNode } from "react"

interface User {
    id: number
    username: string
    role: string
}

interface AuthContextType {
    user: User | null
    token: string | null
    login: (username: string, password: string) => Promise<boolean>
    logout: () => void
    isLoading: boolean
    isAdmin: boolean
}

const AuthContext = createContext<AuthContextType | null>(null)

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "/api"

export function AuthProvider({ children }: { children: ReactNode }) {
    const [user, setUser] = useState<User | null>(null)
    const [token, setToken] = useState<string | null>(null)
    const [isLoading, setIsLoading] = useState(true)

    // Load token from localStorage on mount
    useEffect(() => {
        const storedToken = localStorage.getItem("medquiz_token")
        if (storedToken) {
            setToken(storedToken)
            // Verify token and get user info
            fetchUser(storedToken)
        } else {
            setIsLoading(false)
        }
    }, [])

    const fetchUser = async (accessToken: string) => {
        try {
            const res = await fetch(`${API_BASE}/auth/me`, {
                headers: { Authorization: `Bearer ${accessToken}` }
            })
            if (res.ok) {
                const userData = await res.json()
                setUser(userData)
            } else {
                // Token invalid, clear it
                localStorage.removeItem("medquiz_token")
                setToken(null)
            }
        } catch (err) {
            console.error("Auth check failed:", err)
        } finally {
            setIsLoading(false)
        }
    }

    const login = async (username: string, password: string): Promise<boolean> => {
        try {
            const formData = new URLSearchParams()
            formData.append("username", username)
            formData.append("password", password)

            const res = await fetch(`${API_BASE}/auth/login`, {
                method: "POST",
                headers: { "Content-Type": "application/x-www-form-urlencoded" },
                body: formData
            })

            if (res.ok) {
                const data = await res.json()
                localStorage.setItem("medquiz_token", data.access_token)
                setToken(data.access_token)
                await fetchUser(data.access_token)
                return true
            }
            return false
        } catch (err) {
            console.error("Login failed:", err)
            return false
        }
    }

    const logout = () => {
        localStorage.removeItem("medquiz_token")
        setToken(null)
        setUser(null)
    }

    return (
        <AuthContext.Provider value={{
            user,
            token,
            login,
            logout,
            isLoading,
            isAdmin: user?.role === "admin"
        }}>
            {children}
        </AuthContext.Provider>
    )
}

export function useAuth() {
    const context = useContext(AuthContext)
    if (!context) {
        throw new Error("useAuth must be used within AuthProvider")
    }
    return context
}
