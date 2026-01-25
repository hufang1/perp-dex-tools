import "./globals.css";

export const metadata = {
  title: "HufangPerp Dashboard",
  description: "Spread arb monitoring dashboard",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
