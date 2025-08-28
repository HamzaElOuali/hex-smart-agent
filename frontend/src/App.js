// src/App.js
import React, { useState, useEffect } from "react";
import Sidebar from "./components/Sidebar";
import ChatHeader from "./components/ChatHeader";
import ChatWindow from "./components/ChatWindow";
import ChatInput from "./components/ChatInput";
import WelcomeScreen from "./components/WelcomeScreen";
import API from "./api";
import refineLLMText from "./utils/refineLLMText";
import { SignedIn, SignedOut, RedirectToSignIn, useAuth } from "@clerk/clerk-react";

/* ─── helpers ────────────────────────────────────────────────────────────── */

// Canonical-filename helper: basename → lowercase → strip “_N” suffixes added
// by _safe_filename() on the backend (e.g.  report_3.pdf  ➜  report.pdf)
const canon = (f) =>
  (f || "")
    .replace(/^.*[\\/]/, "") // basename
    .trim()
    .toLowerCase()
    .replace(/_\d+(?=\.[a-z0-9]+$)/, ""); // strip _N before extension

// Your FAQ pool (23 items). We’ll pick 4 at random on an empty chat.
const FAQ_POOL = [
  "How do I complete a Smart Form assigned to me?",
  "Why can't I see my assigned tasks or ITRs on the dashboard?",
  "Where do I upload supporting documents or images for an inspection?",
  "What does the \"A Check\" and \"B Check\" status mean on my task?",
  "How can I tell if a loop test has been completed for my equipment?",
  "I found a defect during inspection — how do I raise a punchlist item?",
  "Can I work offline and sync later?",
  "How do I sign off a completed inspection form digitally?",
  "How do I know if my preservation task is overdue or completed?",
  "How do I track custody transfer from construction to commissioning?",
  "Which loops are tested and which remain incomplete?",
  "How do I prepare a system for mechanical completion or handover?",
  "Where can I find SAT records for System 101?",
  "Can I verify all pre-commissioning forms are completed before startup?",
  "How do I add my approval signature to a turnover certificate?",
  "What are the outstanding punchlists preventing final handover?",
  "How do I assign specific certificate types to a WBS stage or phase?",
  "How can I rename a field like 'Area' to 'Zone' in the app interface?",
  "How do I restrict a subcontractor’s access so they only see their scope?",
  "How do I configure new Smart Form templates with mail merge fields?",
  "Can I change field names without breaking mail merge documents?",
  "How do I audit changes made by users to inspection forms or tasks?",
  "How do I configure notification emails for assigned tasks or expired preservations?"
];

// pick N unique random items
const pickRandom = (arr, n) => {
  const idxs = new Set();
  while (idxs.size < Math.min(n, arr.length)) {
    idxs.add(Math.floor(Math.random() * arr.length));
  }
  return [...idxs].map((i) => arr[i]);
};

// Default chat state
const defaultChats = [
  {
    id: 1,
    title: "Welcome Chat",
    preview: "Hello! I'm your Hex-Doc Agent assistant.",
    messages: [{ text: "Hello! I'm your Hex-Doc Agent assistant.", isUser: false }]
  }
];

export default function App() {
  const { getToken } = useAuth();

  // State Hooks
  const [chats, setChats] = useState(defaultChats);
  const [activeId, setActiveId] = useState(defaultChats[0].id);
  const [input, setInput] = useState("");
  const [selectedFile, setSelectedFile] = useState(null);
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [welcomeSuggestions, setWelcomeSuggestions] = useState([]);

  const activeChat = chats.find((c) => c.id === activeId);

  // Refresh suggestions whenever the active chat is empty (or changes)
  useEffect(() => {
    if (!activeChat || activeChat.messages.length === 0) {
      setWelcomeSuggestions(pickRandom(FAQ_POOL, 4));
    }
  }, [activeId, activeChat]);

  /* ─── message helpers ─────────────────────────────────────────────────── */

  // Append streamed text to last assistant bubble
  const appendText = (chunk) =>
    setChats((cs) =>
      cs.map((c) => {
        if (c.id !== activeId) return c;
        const msgs = [...c.messages];
        msgs[msgs.length - 1] = {
          ...msgs[msgs.length - 1],
          text: msgs[msgs.length - 1].text + refineLLMText(chunk)
        };
        return { ...c, messages: msgs };
      })
    );

  // Attach and deduplicate source references
  const setSources = (sources) =>
    setChats((cs) =>
      cs.map((c) => {
        if (c.id !== activeId) return c;

        const existing = c.messages[c.messages.length - 1]?.sources ?? [];
        const combined = [...existing, ...sources];

        const seen = new Set();
        const uniq = [];
        combined.forEach((s) => {
          const key = `${canon(s.filename)}-${s.page_num ?? "?"}`;
          if (!seen.has(key)) {
            seen.add(key);
            uniq.push(s);
          }
        });

        const msgs = [...c.messages];
        msgs[msgs.length - 1] = { ...msgs[msgs.length - 1], sources: uniq };
        return { ...c, messages: msgs };
      })
    );

  /* ─── handlers: ask / upload / chat mgmt ──────────────────────────────── */

  // Send a question to the backend (SSE streaming).
  // Accepts an optional override so suggestion clicks can send immediately.
  const handleSend = async (questionOverride) => {
    const question = (questionOverride ?? input).trim();
    if (!question) return;
    setInput("");

    // Add user message + empty assistant bubble
    setChats((cs) =>
      cs.map((c) =>
        c.id === activeId
          ? {
              ...c,
              messages: [...c.messages, { text: question, isUser: true }, { text: "", isUser: false }]
            }
          : c
      )
    );

    try {
      const token = await getToken({ template: "backend" });

      const res = await fetch(`${API.defaults.baseURL}/ask?stream=true`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ question, top_k: 6, min_score: 0.3 })
      });

      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // Split on double newline (SSE frame delimiter)
        const frames = buffer.split(/\r?\n\r?\n/);
        buffer = frames.pop(); // Keep incomplete frame

        frames.forEach((frame) => {
          if (!frame.startsWith("data:")) return;
          const data = frame.slice(frame.indexOf(":") + 1).trim();
          if (!data) return;

          let payload;
          try {
            payload = JSON.parse(data);
          } catch {
            return;
          }

          const tokenChunk =
            payload.choices?.[0]?.delta?.content ??
            payload.choices?.[0]?.message?.content ??
            payload.content ??
            payload.answer ??
            payload.text;

          if (tokenChunk) {
            appendText(tokenChunk);
            return;
          }
          if (payload.sources) setSources(payload.sources);
        });
      }
    } catch (err) {
      console.error("Ask error:", err);
      setChats((cs) =>
        cs.map((c) =>
          c.id === activeId
            ? {
                ...c,
                messages: [...c.messages, { text: "⚠️ Error retrieving answer from the agent.", isUser: false }]
              }
            : c
        )
      );
    }
  };

  // Handle PDF file selection & upload
  const handleFileSelect = async (file) => {
    setSelectedFile(file);
    const fileName = file.name;

    setChats((cs) =>
      cs.map((c) =>
        c.id === activeId
          ? { ...c, messages: [...c.messages, { text: `📎 PDF selected: ${fileName}`, isUser: true }] }
          : c
      )
    );

    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("title", fileName);
      formData.append("description", "Uploaded via frontend");
      formData.append("role", "user");

      const token = await getToken({ template: "backend", skipCache: true, forceRefresh: true });
      const res = await API.post("/upload-document", formData, {
        headers: { Authorization: `Bearer ${token}` }
      });

      setChats((cs) =>
        cs.map((c) =>
          c.id === activeId
            ? {
                ...c,
                messages: [
                  ...c.messages,
                  { text: `✅PDF uploaded successfully. The document has been fully processed and divided into ${res.data.chunk_count} semantic chunks for intelligent search and retrieval.`,  isUser: false }
                ]
              }
            : c
        )
      );
      setSelectedFile(null);
    } catch (err) {
      console.error("Upload failed:", err);
      setChats((cs) =>
        cs.map((c) =>
          c.id === activeId
            ? {
                ...c,
                messages: [
                  ...c.messages,
                  { text: `❌ Upload failed: ${err.response?.data?.detail || err.message}`, isUser: false }
                ]
              }
            : c
        )
      );
    }
  };

  // Create a new chat
  const handleNewChat = () => {
    const newId = Math.max(...chats.map((c) => c.id)) + 1;
    setChats([{ id: newId, title: `Chat ${newId}`, preview: "New chat started.", messages: [] }, ...chats]);
    setActiveId(newId);
  };

  const handleSelect = (id) => setActiveId(id);

  /* ─── UI Render ────────────────────────────────────────────────────────── */

  return (
    <>
      <SignedOut>
        <RedirectToSignIn />
      </SignedOut>

      <SignedIn>
        <div className="h-screen flex bg-gray-100">
          <Sidebar
            chats={chats}
            onNewChat={handleNewChat}
            onSelect={handleSelect}
            activeId={activeId}
            isOpen={isSidebarOpen}
            onToggle={() => setIsSidebarOpen(!isSidebarOpen)}
          />

          <div className="flex-1 flex flex-col">
            <ChatHeader
              isSidebarOpen={isSidebarOpen}
              onSidebarToggle={() => setIsSidebarOpen(!isSidebarOpen)}
            />

            {activeChat?.messages.length === 0 ? (
              <WelcomeScreen
                suggestions={welcomeSuggestions}
                onPick={(q) => handleSend(q)}
              />
            ) : (
              <ChatWindow messages={activeChat.messages} />
            )}

            <div className="w-full flex items-center justify-center">
              <ChatInput value={input} onChange={setInput} onSend={() => handleSend()} onFileSelect={handleFileSelect} />
            </div>

            {selectedFile && (
              <div className="px-8 pb-2 text-sm text-gray-600 flex items-center gap-2">
                <span>📎</span> <span>{selectedFile.name}</span>
              </div>
            )}
          </div>
        </div>
      </SignedIn>
    </>
  );
}
