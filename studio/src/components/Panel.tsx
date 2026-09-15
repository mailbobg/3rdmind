import type { ReactNode } from "react";
import { Card } from "@astryxdesign/core/Card";
import { Layout, LayoutContent, LayoutFooter, LayoutHeader, HStack } from "@astryxdesign/core/Layout";
import { Text } from "@astryxdesign/core/Text";

/** A titled card with an optional status line at the top right and a footer note: the one big thing in a column. */
export function Panel(p: { title: ReactNode; status?: ReactNode; statusTone?: "ok" | "bad"; footer?: ReactNode; children: ReactNode; flush?: boolean }) {
  return (
    <Card padding={0}>
      <Layout
        height="auto"
        header={
          <LayoutHeader hasDivider paddingBlockEnd={2}>
            <HStack gap={2} align="center" justify="between">
              <Text weight="semibold">{p.title}</Text>
              {p.status && <Text type="supporting" color={p.statusTone === "bad" ? "primary" : "secondary"}>{p.status}</Text>}
            </HStack>
          </LayoutHeader>
        }
        content={<LayoutContent padding={p.flush ? 0 : 3} isScrollable={false}>{p.children}</LayoutContent>}
        footer={p.footer ? <LayoutFooter hasDivider><Text type="supporting">{p.footer}</Text></LayoutFooter> : undefined}
      />
    </Card>
  );
}
