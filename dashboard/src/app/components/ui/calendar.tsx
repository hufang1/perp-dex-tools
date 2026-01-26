"use client";

import * as React from "react";
import { DayPicker } from "react-day-picker";

import { cn } from "@/app/lib/utils";

export type CalendarProps = React.ComponentProps<typeof DayPicker>;

function Calendar({ className, classNames, showOutsideDays = true, ...props }: CalendarProps) {
  return (
    <DayPicker
      showOutsideDays={showOutsideDays}
      className={cn("p-2", className)}
      classNames={{
        months: "flex flex-col gap-4",
        month: "space-y-4",
        caption: "flex justify-between items-center px-2",
        caption_label: "text-sm font-medium text-white",
        nav: "flex items-center gap-1",
        nav_button: "h-7 w-7 rounded-md border border-white/10 text-white/80 hover:text-white",
        table: "w-full border-collapse",
        head_row: "flex",
        head_cell: "text-white/60 w-8 text-xs",
        row: "flex w-full mt-2",
        cell: "relative p-0 text-center text-sm w-8 h-8",
        day: "h-8 w-8 rounded-md hover:bg-white/10",
        day_selected: "bg-white/20 text-white",
        day_today: "border border-white/30",
        day_outside: "text-white/30",
        day_disabled: "text-white/20",
        ...classNames,
      }}
      {...props}
    />
  );
}
Calendar.displayName = "Calendar";

export { Calendar };
