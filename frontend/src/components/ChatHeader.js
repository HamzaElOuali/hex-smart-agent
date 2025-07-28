import { ChevronLeft } from "lucide-react";

export default function ChatHeader({ isSidebarOpen, onSidebarToggle }) {
  return (
    <div className="flex items-center gap-4 border-b px-8 py-4 relative">
      {/* Show the arrow only on mobile, and only when sidebar is open */}
      <button
        className="md:hidden absolute left-4 top-1/2 -translate-y-1/2"
        onClick={onSidebarToggle}
        aria-label={isSidebarOpen ? "Close sidebar" : "Open sidebar"}
      >
        <ChevronLeft className="w-7 h-7 text-gray-500" />
      </button>
      <img
        src="/bot-icon.png"
        alt="Bot Icon"
        className="w-12 h-12 object-contain ml-10 md:ml-0"
        style={{ background: "none" }}
      />
      <div>
        <div className="font-bold text-lg">Hex-Doc Agent</div>
        <div className="text-gray-500 text-sm">
          Your intelligent documentation assistant
        </div>
      </div>
    </div>
  );
}
