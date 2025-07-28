import React from "react";
import { UserButton, useUser } from "@clerk/clerk-react";

export default function Sidebar({
  chats,
  onNewChat,
  onSelect,
  activeId,
  isOpen,
  onToggle,
}) {
  const { user } = useUser(); // Clerk user object

  return (
    <div
      className={`
        fixed md:static top-0 left-0 z-40 h-full bg-white border-r
        transition-all duration-300 flex flex-col
        ${isOpen ? "w-64" : "w-0 md:w-64"}
        overflow-hidden
      `}
    >
      {/* ─── Logo / Close (mobile) ───────────────────────── */}
      <div className="relative flex flex-col items-center gap-2 p-6 border-b">
        <img src="/logo-jesa.png" alt="Logo JESA" className="w-24 h-auto" />

        <button
          onClick={onToggle}
          className="absolute top-4 right-4 md:hidden text-gray-600 hover:text-black text-2xl px-2"
          aria-label="Fermer la sidebar"
        >
          ✕
        </button>
      </div>

      {/* ─── New Chat button ─────────────────────────────── */}
      <button
        className="mx-6 my-4 w-[calc(100%-3rem)] py-3 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 transition text-base"
        onClick={onNewChat}
      >
        + New Chat
      </button>

      {/* ─── Chat list ───────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto px-2">
        {chats.map((chat) => (
          <div
            key={chat.id}
            className={`my-1 px-4 py-2 rounded-lg cursor-pointer ${
              activeId === chat.id
                ? "bg-blue-50 border border-blue-500"
                : "hover:bg-gray-100"
            }`}
            onClick={() => onSelect(chat.id)}
          >
            <div className="font-medium">{chat.title}</div>
            <div className="text-xs text-gray-500">{chat.preview}</div>
          </div>
        ))}
      </div>

      {/* ─── User strip at bottom ────────────────────────── */}
      {user && (
        <div className="w-full border-t p-4 flex items-center gap-3">
          {/* Single avatar that opens Clerk menu */}
          <UserButton
            afterSignOutUrl="/"
            appearance={{ elements: { avatarBox: "w-8 h-8" } }}
          />

          {/* User’s full name */}
          <span className="text-sm font-medium truncate">{user.fullName}</span>
        </div>
      )}
    </div>
  );
}
