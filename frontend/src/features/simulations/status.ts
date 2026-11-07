export const STATUS_TONE: Record<string, "default" | "brand" | "pos" | "neg" | "warn" | "info"> = {
  draft: "default", building_graph: "info", graph_ready: "brand", preparing: "info", ready: "brand", queued: "warn", running: "warn",
  paused: "warn", completed: "pos", failed: "neg", cancelled: "default",
};

export const STATUS_LABEL: Record<string, string> = {
  draft: "Draft", building_graph: "Building graph", graph_ready: "Graph ready", preparing: "Preparing", ready: "Ready to run", queued: "Queued",
  running: "Running", paused: "Paused", completed: "Completed", failed: "Failed", cancelled: "Cancelled",
};
