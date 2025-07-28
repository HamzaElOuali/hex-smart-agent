// src/SignInPage.js
import { SignIn } from "@clerk/clerk-react";

export default function SignInPage() {
  return (
    <div className="h-screen flex items-center justify-center">
      <SignIn path="/sign-in/*" routing="path" signUpUrl="/sign-up" />
    </div>
  );
}
