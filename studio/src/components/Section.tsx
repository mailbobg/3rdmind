import type { ReactNode } from "react";
import { Card } from "@astryxdesign/core/Card";
import { VStack, HStack } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";

/** A results-column block: heading row with a muted note on the right, then content. */
export function Section(p: { title: string; note?: ReactNode; children: ReactNode }) {
  return (
    <Card padding={3}>
      <VStack gap={2}>
        <HStack gap={2} align="center" justify="between">
          <Text weight="semibold">{p.title}</Text>
          {p.note && <Text type="supporting">{p.note}</Text>}
        </HStack>
        {p.children}
      </VStack>
    </Card>
  );
}
