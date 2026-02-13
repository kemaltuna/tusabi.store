# System Architecture & Migration Guide

> **Purpose**: This document serves as the **Source of Truth** for the MedQuiz Pro system architecture. It details the transition from the legacy Streamlit Monolith to a scalable **Next.js + FastAPI** Microservice Architecture.

## 1. High-Level Architecture

### A. Legacy Monolith (Current Production)
*   **UI**: Streamlit (`app.py`) - Server-side rendering, session state management.
*   **Logic**: Direct Python calls to `database.py`, `generation_engine.py`.
*   **Data**: SQLite (`data/quiz.db`) + Flat Files (`preprocessed_chunks/`).

### B. Modern Stack (Target Architecture)
*   **Frontend**: **Next.js 15+** (App Router, React 19).
    *   **UI Framework**: Tailwind CSS + shadcn/ui.
    *   **State Management**: TanStack Query (React Query) for server state, Zustand for client state.
    *   **Rendering**: Server Components (RSC) where possible, Client Components for interactivity.
*   **Backend**: **FastAPI** (Python 3.10+).
    *   **Role**: REST API for Quiz Logic, AI Generation, and User Management.
    *   **Documentation**: Open Standard (OpenAPI/Swagger) at `/docs`.
*   **Data Layer**:
    *   **Database**: SQLite (`data/quiz_v2.db` - Cloned from Prod).
    *   **Content Library**: Read-only access to `preprocessed_chunks/` (Shared volume).

---

## 2. Safe Migration Strategy (Zero Data Loss)

To ensure safety ("test as a different application"), we will **Clone** the production database to a development instance.

1.  **Snapshot**: Create `data/quiz_v2.db` as a direct copy of `data/quiz.db`.
2.  **Isolation**: The New App (FastAPI) will ONLY write to `quiz_v2.db`. The Legacy App (`app.py`) continues to use `quiz.db`.
3.  **Verification**: We will manually verify that questions, progress, and highlights appear correctly in the new app.
4.  **Cutover (Future)**: Once validated, we sync the latest data and deprecate the Streamlit app.

---

## 3. Directory Structure (Target)

```bash
/home/yusuf-kemal-tuna/medical_quiz_app/
├── app.py                  # [LEGACY] Streamlit App (Kept running for comparison)
├── backend/                # [NEW] FastAPI Application
│   ├── main.py             # Entry Point & CORS Setup
│   ├── database.py         # SQLAlchemy / SQLModel implementation (Ported from root)
│   ├── routers/            # API Routes
│   │   ├── quiz.py         # /quiz endpoints
│   │   ├── library.py      # /library endpoints
│   │   └── ai.py           # /generate endpoints
│   ├── services/           # Business Logic
│   │   ├── generator.py    # Migrated GenerationEngine
│   │   └── space_rep.py    # Spaced Repetition Logic (SM-2)
│   └── models/             # Pydantic Schemas
├── frontend/               # [NEW] Next.js Application
│   ├── app/                # App Router Pages
│   ├── components/         # Reusable UI (Card, Sidebar, etc.)
│   ├── lib/                # API Clients & Utils
│   └── ...
├── data/                   # Data Storage
│   ├── quiz.db             # PROD DB (Streamlit)
│   ├── quiz_v2.db          # DEV DB (FastAPI/Next.js)
│   └── medquiz_library.json
└── ...
```

---

## 4. Backend API Specification (FastAPI)

The backend will expose strictly typed REST endpoints.

| Domain | Method | Endpoint | Description |
| :--- | :--- | :--- | :--- |
| **Quiz** | `GET` | `/quiz/next` | Get next card. Params: `mode` (new/review), `topic`, `subtopic`. |
| | `POST` | `/quiz/submit` | Submit answer/grade. Updates SM-2 algo in DB. |
| | `GET` | `/quiz/card/{id}` | Get specific card details by ID. |
| **Library** | `GET` | `/library/structure` | Returns full taxonomy (`medquiz_library.json`). |
| | `GET` | `/library/stats` | Returns user progress stats per topic. |
| **AI** | `POST` | `/ai/generate` | Trigger Question Generation Job. Body: `{concept, source}`. |
| | `GET` | `/ai/jobs/{id}` | Check status of generation job. |
| **Highlights** | `GET` | `/highlights/{card_id}` | Get highlights for a card. |
| | `POST` | `/highlights` | Save/Sync highlights. |

---

## 5. Frontend Component Architecture (Next.js)

### Core Components
1.  **`QuizCard`**: The central component.
    *   Displays Question (HTML/Markdown).
    *   Handles Option Selection.
    *   Displays Explanation (Revealed state).
    *   **Features**: Text Highlighting integration (Select-to-highlight).
    *   **Math Support**: KaTeX rendering for formulas.
2.  **`SidebarLayout`**: Persistent navigation.
    *   Displays Topic Tree (Anatomi -> Subtopic).
    *   Shows "Due Review" Badges (fetched via React Query).
3.  **`Dashboard`**: Home view.
    *   GridView of Subjects with Progress Bars.
    *   "Quick Start" button for Reviews.

---

## 6. Implementation Stages

### Phase 1: Foundation Setup
*   Initialize `backend/` (FastAPI + Pydantic models).
*   Initialize `frontend/` (Next.js + Tailwind).
*   Script: `scripts/clone_db.py` to create `quiz_v2.db`.

### Phase 2: Read-Only Parity
*   Implement `GET /library` and `GET /quiz/next`.
*   Build Frontend Sidebar and Card Display.
*   **Goal**: User can browse topics and see existing questions from `quiz_v2.db` (The "Library Transfer" test).

### Phase 3: Interactive Parity
*   Implement `POST /quiz/submit` (Spaced Repetition).
*   Implement Highlighting system (Frontend <-> API).
*   **Goal**: User can actually play the quiz and save progress.

### Phase 4: AI Generation
*   Port `generation_engine.py` to `backend/services/`.
*   Connect `POST /ai/generate`.
*   **Goal**: Full feature parity with Legacy App.
