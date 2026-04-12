import { Fraunces, Manrope } from "next/font/google";
import "./globals.css";
import { AppThemeProvider } from "./lib/theme";

const displayFont = Fraunces({
  subsets: ["latin"],
  variable: "--font-display",
  display: "swap"
});

const bodyFont = Manrope({
  subsets: ["latin"],
  variable: "--font-body",
  display: "swap"
});

export const metadata = {
  title: "Agentic Workflow Studio",
  description:
    "A planner-executor workflow platform for authoring and executing AI-powered workflows through chat, compose, and a visual DAG editor."
};

export default function RootLayout({
  children
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${displayFont.variable} ${bodyFont.variable} min-h-screen font-body`}>
        <AppThemeProvider>
          <div className="w-full px-6 py-8">{children}</div>
        </AppThemeProvider>
      </body>
    </html>
  );
}
