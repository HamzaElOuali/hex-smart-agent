// src/App.js
import React, { useState } from "react";
import Sidebar from "./components/Sidebar";
import ChatHeader from "./components/ChatHeader";
import ChatWindow from "./components/ChatWindow";
import ChatInput from "./components/ChatInput";
import WelcomeScreen from "./components/WelcomeScreen";
import API from "./api";
import refineLLMText from "./utils/refineLLMText";

import {
  SignedIn,
  SignedOut,
  RedirectToSignIn,
  useAuth,
} from "@clerk/clerk-react";

/* ─── default chat ────────────────────────────────────────────── */
const defaultChats = [
  {
    id: 1,
    title: "Welcome Chat",
    preview: "Hello! I'm your Hex-Doc Agent assistant.",
    messages: [{ text: "Hello! I'm your Hex-Doc Agent assistant.", isUser: false }],
  },
];

export default function App() {
  /* Clerk */
  const { getToken } = useAuth();

  /* State */
  const [chats, setChats] = useState(defaultChats);
  const [activeId, setActiveId] = useState(chats[0].id);
  const [input, setInput] = useState("");
  const [selectedFile, setSelectedFile] = useState(null);
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);

  const activeChat = chats.find((c) => c.id === activeId);

  /* ─────────── helpers to mutate chat state ─────────────────── */
  const appendText = (chunk) =>
    setChats((cs) =>
      cs.map((c) => {
        if (c.id !== activeId) return c;
        const msgs = [...c.messages];
        const lastIdx = msgs.length - 1;
        msgs[lastIdx] = { ...msgs[lastIdx], text: msgs[lastIdx].text + refineLLMText(chunk) };
        return { ...c, messages: msgs };
      })
    );

  const setSources = (sources) =>
    setChats((cs) =>
      cs.map((c) => {
        if (c.id !== activeId) return c;
        const msgs = [...c.messages];
        const lastIdx = msgs.length - 1;
        msgs[lastIdx] = { ...msgs[lastIdx], sources };
        return { ...c, messages: msgs };
      })
    );

  /* ───────────── handleSend (SSE streaming) ───────────── */
  const handleSend = async () => {
    if (!input.trim()) return;
    const question = input;
    setInput("");

    /* push user message + empty assistant bubble */
    setChats((cs) =>
      cs.map((c) =>
        c.id === activeId
          ? {
              ...c,
              messages: [
                ...c.messages,
                { text: question, isUser: true },
                { text: "", isUser: false },
              ],
            }
          : c
      )
    );

    try {
      const token = await getToken({ template: "backend" });

      const res = await fetch(`${API.defaults.baseURL}/ask?stream=true`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ question, top_k: 6, min_score: 0.3 }),
      });

      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        /* split on double newline == SSE frame delimiter */
        const frames = buffer.split(/\n\n/);
        buffer = frames.pop(); // keep incomplete frame

        frames.forEach((frame) => {
          if (!frame.startsWith("data: ")) return;
          const data = frame.slice(6).trim();
          if (!data) return;

          let payload;
          try {
            payload = JSON.parse(data);
          } catch {
            return;
          }

          /* extract token in every known shape */
          const tokenChunk =
            /* OpenRouter / OpenAI streaming (delta) */
            payload.choices?.[0]?.delta?.content ??
            /* Some models use message.content */
            payload.choices?.[0]?.message?.content ??
            /* Generic single‑field content */
            payload.content ??
            /* Legacy non‑stream JSON */
            payload.answer ??
            /* Very old plain‑text field */
            payload.text;

          if (tokenChunk) {
            appendText(tokenChunk);
            return;
          }

          /* final sources frame */
          if (payload.sources) {
            setSources(payload.sources);
          }
        });
      }
    } catch (err) {
      console.error("Ask error:", err);
      setChats((cs) =>
        cs.map((c) =>
          c.id === activeId
            ? {
                ...c,
                messages: [
                  ...c.messages,
                  { text: "⚠️ Error retrieving answer from the agent.", isUser: false },
                ],
              }
            : c
        )
      );
    }
  };

  /* ───────────── handleFileSelect (unchanged) ───────────── */
  const handleFileSelect = async (file) => {
    setSelectedFile(file);
    const fileName = file.name;

    /* bubble showing selected file */
    setChats((cs) =>
      cs.map((c) =>
        c.id === activeId
          ? {
              ...c,
              messages: [...c.messages, { text: `📎 PDF sélectionné : ${fileName}`, isUser: true }],
            }
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
        headers: { Authorization: `Bearer ${token}` },
      });

      setChats((cs) =>
        cs.map((c) =>
          c.id === activeId
            ? {
                ...c,
                messages: [
                  ...c.messages,
                  { text: `✅ PDF uploaded (${res.data.chunk_count} chunks)`, isUser: false },
                ],
              }
            : c
        )
      );
      /* clear banner */
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
                  {
                    text: `❌ Upload failed: ${err.response?.data?.detail || err.message}`,
                    isUser: false,
                  },
                ],
              }
            : c
        )
      );
    }
  };

  /* new chat & select */
  const handleNewChat = () => {
    const newId = Math.max(...chats.map((c) => c.id)) + 1;
    setChats([{ id: newId, title: `Chat ${newId}`, preview: "New chat started.", messages: [] }, ...chats]);
    setActiveId(newId);
  };

  const handleSelect = (id) => setActiveId(id);

  /* ───────────── UI ───────────── */
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
              <WelcomeScreen />
            ) : (
              <ChatWindow messages={activeChat.messages} />
            )}

            <div className="w-full flex items-center justify-center">
              <ChatInput
                value={input}
                onChange={setInput}
                onSend={handleSend}
                onFileSelect={handleFileSelect}
              />
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
