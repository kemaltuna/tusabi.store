import { QuizCardData, LibraryNode } from "./types";

const API_Base = "/api";

function getAuthHeader(): Record<string, string> {
    if (typeof window === 'undefined') return {};
    const token = localStorage.getItem("medquiz_token");
    if (!token) return {};
    return { Authorization: `Bearer ${token}` };
}

export async function fetchNextCard(mode: string = "standard", topic?: string): Promise<QuizCardData | null> {
    const params = new URLSearchParams({ mode });
    if (topic) params.append("topic", topic);

    const res = await fetch(`${API_Base}/quiz/next?${params.toString()}`, {
        headers: getAuthHeader()
    });
    if (!res.ok) throw new Error("Failed to fetch card");

    const data = await res.json();
    return data as QuizCardData; // null is valid if no cards
}

export async function submitReview(questionId: number, grade: string): Promise<void> {
    const res = await fetch(`${API_Base}/quiz/submit`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            ...getAuthHeader()
        },
        body: JSON.stringify({ question_id: questionId, grade }),
    });
    if (!res.ok) throw new Error("Failed to submit review");
}

export async function submitFeedback(questionId: number, type: string, description: string): Promise<void> {
    const res = await fetch(`${API_Base}/quiz/feedback`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            ...getAuthHeader()
        },
        body: JSON.stringify({
            question_id: questionId,
            feedback_type: type,
            description: description
        }),
    });
    if (!res.ok) throw new Error("Failed to submit feedback");
}

export async function fetchLibrary(): Promise<LibraryNode> {
    const res = await fetch(`${API_Base}/library/structure`);
    if (!res.ok) throw new Error("Failed to fetch library");
    return res.json();
}

export const adminApi = {
    async getGenerationJobs() {
        try {
            const response = await fetch(`${API_Base}/admin/jobs?limit=10`, {
                headers: getAuthHeader()
            });
            if (!response.ok) return [];
            return response.json();
        } catch (error) {
            console.error('Failed to fetch jobs:', error);
            return [];
        }
    }
};
