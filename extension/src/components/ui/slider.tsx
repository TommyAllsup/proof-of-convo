import * as React from "react";

import { cn } from "../../lib/cn";

export interface SliderProps extends React.InputHTMLAttributes<HTMLInputElement> {
  value: number;
}

export function Slider({ className, value, ...props }: SliderProps) {
  return (
    <input
      type="range"
      value={value}
      className={cn("h-2 w-full accent-primary", className)}
      {...props}
    />
  );
}

