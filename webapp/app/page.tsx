import type { Metadata } from "next";
import AtlasApp from "./AtlasApp";

export const metadata: Metadata = {
  title: "Research Connections Atlas",
  description: "Explore how faculty connect through publications, research themes, and potential intellectual overlap.",
};

export default function Home() {
  return <AtlasApp />;
}
