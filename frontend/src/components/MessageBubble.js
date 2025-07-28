import React from "react";

export default function MessageBubble({ text, isUser }) {
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-2`}>
      <div
        className={`
          max-w-[70%] px-4 py-2 rounded-2xl shadow 
          ${isUser 
            ? "bg-blue-600 text-white rounded-br-md"
            : "bg-gray-200 text-gray-900 rounded-bl-md"}
        `}
      >
        {text}
      </div>
    </div>
  );
}
