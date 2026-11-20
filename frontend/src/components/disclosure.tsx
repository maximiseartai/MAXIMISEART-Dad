import * as React from "react"
import { ChevronDownIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"

export function Disclosure({
  label,
  defaultOpen = false,
  className,
  children,
}: {
  label: React.ReactNode
  defaultOpen?: boolean
  className?: string
  children: React.ReactNode
}) {
  return (
    <Collapsible defaultOpen={defaultOpen} className={className}>
      <CollapsibleTrigger render={<Button variant="ghost" size="sm" className="group -ml-2" />}>
        {label}
        <ChevronDownIcon
          data-icon="inline-end"
          className="transition-[rotate] duration-200 ease-out group-data-[panel-open]:rotate-180"
        />
      </CollapsibleTrigger>
      <CollapsibleContent>{children}</CollapsibleContent>
    </Collapsible>
  )
}
