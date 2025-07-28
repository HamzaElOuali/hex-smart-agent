// src/components/ChatWindow.js
import { useEffect, useRef } from "react";

export default function ChatWindow({ messages }) {
  const bottomRef = useRef(null);

  /* auto‑scroll to newest bubble */
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  return (
    <div className="flex-1 overflow-auto px-8 py-6 flex flex-col gap-4 items-center bg-transparent">
      <div className="w-full max-w-2xl flex flex-col gap-4">
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex ${msg.isUser ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`px-4 py-3 rounded-2xl shadow relative
                ${
                  msg.isUser
                    ? "bg-blue-600 text-white self-end"
                    : "bg-gray-100 text-gray-800 self-start"
                }
                max-w-[75%] break-words text-base whitespace-pre-wrap
              `}
            >
              {/* message body */}
              {msg.isUser ? (
                msg.text || <span className="opacity-50">…</span>
              ) : msg.text ? (
                <span
                  dangerouslySetInnerHTML={{ __html: msg.text }}
                />
              ) : (
                <span className="opacity-50">…</span>
              )}

              {/* optional source footnotes */}
              {msg.sources?.length > 0 && (
                <div className="mt-2 text-[11px] text-gray-500 space-y-0.5">
                  {msg.sources.map((s, idx) => (
                    <div key={idx}>
                      📄 {s.title} — page {s.page_num ?? "?"}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}

        {/* scroll anchor */}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
