import type { ReactNode } from "react";
import { Layout, LayoutContent, LayoutHeader, LayoutPanel, VStack, HStack } from "@astryxdesign/core/Layout";
import { ResizeHandle, useResizable } from "@astryxdesign/core/Resizable";
import { Toolbar } from "@astryxdesign/core/Toolbar";
import { Button } from "@astryxdesign/core/Button";
import { Heading, Text } from "@astryxdesign/core/Text";
import { Badge } from "@astryxdesign/core/Badge";
import { useStudio } from "../hooks/studioContext";

export interface PageFrameProps {
  /** Object bar: what is being worked on. */
  title: string;
  description?: string;
  tag?: string;
  titleEnd?: ReactNode;
  /** Middle column head: left slot (tabs) and right slot (actions). */
  tabs?: ReactNode;
  actions?: ReactNode;
  /** Middle column body. */
  children: ReactNode;
  /** Results column head and body; the column is collapsible and resizable. */
  resultsTitle: ReactNode;
  resultsActions?: ReactNode;
  results: ReactNode;
}

/**
 * The three-layer frame every Studio page shares: an object bar across both columns, then a work column
 * (tabs + actions toolbar, then content) beside a resizable results panel that the user can hide.
 */
export function PageFrame(p: PageFrameProps) {
  const { layout } = useStudio();
  const panel = useResizable({ defaultSize: 680, minSize: 360, maxSize: 1400, autoSaveId: "studio-results" });
  const toggle = <Button size="sm" variant="ghost" label={layout.resultsOpen ? "隐藏结果 ▸" : "◂ 显示结果"} onClick={layout.toggleResults} />;

  return (
    <Layout
      height="fill"
      header={
        <LayoutHeader hasDivider paddingBlockEnd={2}>
          <HStack gap={3} align="center" justify="between">
            <VStack gap={0}>
              <Heading level={4} accessibilityLevel={1}>{p.title}</Heading>
              {p.description && <Text type="supporting" maxLines={1}>{p.description}</Text>}
            </VStack>
            <HStack gap={2} align="center">
              {p.titleEnd}
              {p.tag && <Badge label={p.tag} />}
            </HStack>
          </HStack>
        </LayoutHeader>
      }
      content={
        <Layout
          height="fill"
          header={
            <Toolbar label="工作区操作" size="sm" dividers={["bottom"]} startContent={p.tabs} endContent={<>{p.actions}{toggle}</>} />
          }
          content={<LayoutContent padding={3}>{p.children}</LayoutContent>}
        />
      }
      end={
        layout.resultsOpen ? (
          <>
            <ResizeHandle direction="horizontal" hasDivider resizable={panel.props} label="调整结果栏宽度" />
            <LayoutPanel width={panel.size} hasDivider={false} padding={0} label="结果">
              <Layout
                height="fill"
                header={<Toolbar label="结果操作" size="sm" dividers={["bottom"]} startContent={<Text weight="semibold">{p.resultsTitle}</Text>} endContent={p.resultsActions} />}
                content={<LayoutContent padding={3}>{p.results}</LayoutContent>}
              />
            </LayoutPanel>
          </>
        ) : undefined
      }
    />
  );
}
