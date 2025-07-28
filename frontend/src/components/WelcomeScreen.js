export default function WelcomeScreen() {
  return (
    <div className="h-full flex flex-col items-center justify-center text-center text-gray-500">
      <img
        src="/bot-icon.png"
        alt="Bot Icon"
        className="w-20 h-20 mb-4 object-contain"
        style={{ background: "none" }}
      />
      <div className="text-2xl font-bold mb-2">Welcome to Hex-Doc Agent</div>
      <div className="mb-8">
        Your intelligent documentation assistant is ready to help.<br/>
        Start a conversation by typing a message below!
      </div>
    </div>
  );
}
