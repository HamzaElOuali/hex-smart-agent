export default function WelcomeScreen({ suggestions = [], onPick }) {
  return (
    <div className="h-full flex flex-col items-center justify-center text-center text-gray-600">
      <img
        src="/bot-icon.png"
        alt="Bot Icon"
        className="w-20 h-20 mb-4 object-contain"
        style={{ background: "none" }}
      />
      <div className="text-2xl font-bold mb-2">Welcome to JES-AI</div>
      <div className="mb-6">
        Your intelligent documentation assistant is ready to help.<br />
        Try one of these:
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 w-full max-w-3xl px-6">
        {suggestions.map((q, i) => (
          <button
            key={i}
            className="text-left bg-white border hover:shadow rounded-xl px-4 py-3 transition"
            onClick={() => onPick(q)}
            title={q}
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}
