import { CirclePlus, Send } from "lucide-react";
import React, { useRef } from "react";

export default function ChatInput({ value, onChange, onSend, onFileSelect }) {
  const fileInputRef = useRef();

  const handleFileClick = () => {
    fileInputRef.current.click();
  };

  return (
    <form
      className="flex w-[70%] justify-center items-center gap-2 px-8 py-4 border-t"
      onSubmit={e => {
        e.preventDefault();
        onSend();
      }}
    >
      {/* BOUTON + POUR UPLOAD */}
      <button
        type="button"
        className="w-10 h-10 bg-gray-200 hover:bg-gray-300 rounded-lg flex items-center justify-center text-xl text-gray"
        onClick={handleFileClick}
        title="Ajouter un PDF"
      >
        <CirclePlus />
      </button>
      <input
        type="file"
        accept=".pdf"
        style={{ display: "none" }}
        ref={fileInputRef}
        onChange={e => {
          if (e.target.files.length > 0) {
            onFileSelect(e.target.files[0]);
          }
        }}
      />
      <input
        type="text"
        className="flex-1 rounded-lg border px-4 py-2 focus:outline-none focus:ring-2 focus:ring-blue-400"
        placeholder="Ask Hex-Doc Agent anything..."
        value={value}
        onChange={e => onChange(e.target.value)}
      />
      <button
        type="submit"
        className="bg-blue-600 text-white px-3 py-2 rounded-lg hover:bg-blue-700 transition"
      >
        <Send />
      </button>
    </form>
  );
}
