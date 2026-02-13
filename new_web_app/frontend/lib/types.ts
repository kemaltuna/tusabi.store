export interface Question {
    id: number;
    source_material: string | null;
    category: string | null;
    topic: string | null;
    question_text: string;
    options: (string | { id: string; text: string })[];  // Some questions have object options
    correct_answer_index: number;
    explanation_data?: any;
    tags?: string[];
}

export interface ReviewState {
    ease_factor: number;
    interval: number;
    repetitions: number;
    next_review_date: string | null;
}

export type QuizCardData = Question & ReviewState;

export interface LibraryNode {
    [key: string]: LibraryNode | string[];
}
