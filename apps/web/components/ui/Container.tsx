import type { ElementType, ReactNode } from "react";

import { cn } from "@/lib/cn";

type ContainerProps = {
  as?: ElementType;
  className?: string;
  children: ReactNode;
};

export function Container({ as: As = "div", className, children }: ContainerProps) {
  return <As className={cn("container-page", className)}>{children}</As>;
}
