"use client";

import * as React from "react";
import { format } from "date-fns";
import { Calendar } from "@/app/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/app/components/ui/popover";
import { Button } from "@/app/components/ui/button";
import { cn } from "@/app/lib/utils";

export function DateTimePicker({
  value,
  onChange,
  placeholder,
}: {
  value?: Date;
  onChange: (date?: Date) => void;
  placeholder?: string;
}) {
  const [time, setTime] = React.useState<string>(value ? format(value, "HH:mm") : "00:00");

  React.useEffect(() => {
    if (value) {
      setTime(format(value, "HH:mm"));
    }
  }, [value]);

  const handleDateSelect = (date?: Date) => {
    if (!date) {
      onChange(undefined);
      return;
    }
    const [hh, mm] = time.split(":").map((v) => parseInt(v, 10));
    const next = new Date(date);
    if (!Number.isNaN(hh)) next.setHours(hh);
    if (!Number.isNaN(mm)) next.setMinutes(mm);
    next.setSeconds(0, 0);
    onChange(next);
  };

  const handleTimeChange = (next: string) => {
    setTime(next);
    if (!value) return;
    const [hh, mm] = next.split(":").map((v) => parseInt(v, 10));
    const nextDate = new Date(value);
    if (!Number.isNaN(hh)) nextDate.setHours(hh);
    if (!Number.isNaN(mm)) nextDate.setMinutes(mm);
    nextDate.setSeconds(0, 0);
    onChange(nextDate);
  };

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className={cn("gap-2", !value && "text-white/50")}>
          {value ? format(value, "MM:dd HH:mm") : placeholder ?? "选择时间"}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[260px]">
        <Calendar mode="single" selected={value} onSelect={handleDateSelect} />
        <div className="mt-2 flex items-center gap-2">
          <label className="text-xs text-white/60">时间</label>
          <input
            type="time"
            value={time}
            onChange={(e) => handleTimeChange(e.target.value)}
            className="h-8 flex-1 rounded-md border border-white/10 bg-transparent px-2 text-sm text-white"
          />
        </div>
      </PopoverContent>
    </Popover>
  );
}
