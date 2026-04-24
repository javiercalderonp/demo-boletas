import Image from "next/image";
import Link from "next/link";

type BrandLogoProps = {
  size?: "sm" | "md" | "lg";
  href?: string;
  priority?: boolean;
  className?: string;
};

const sizeClasses = {
  sm: "w-40 h-auto",
  md: "w-52 h-auto",
  lg: "w-80 h-auto",
};

export function BrandLogo({
  size = "md",
  href,
  priority = false,
  className = "",
}: BrandLogoProps) {
  const image = (
    <Image
      src="/logo.png"
      alt="Expense Ops"
      width={1536}
      height={1024}
      priority={priority}
      className={`${sizeClasses[size]} ${className}`.trim()}
    />
  );

  if (!href) {
    return image;
  }

  return (
    <Link href={href} aria-label="Expense Ops" className="inline-block">
      {image}
    </Link>
  );
}
