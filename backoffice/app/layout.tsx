import "./globals.css";

import { Providers } from "./providers";

export const metadata = {
  title: "Expense Ops",
  description: "Backoffice operativo",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
