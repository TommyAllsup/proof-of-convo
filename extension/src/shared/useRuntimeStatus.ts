import * as React from "react";

import type { RuntimeStatus, StatusUpdateMessage } from "./messages";
import { sendRuntimeMessage } from "./chrome";

const INITIAL_STATUS: RuntimeStatus = {
  captureState: "idle",
  backendState: "disconnected",
  updatedAt: Date.now()
};

export function useRuntimeStatus() {
  const [status, setStatus] = React.useState<RuntimeStatus>(INITIAL_STATUS);

  React.useEffect(() => {
    sendRuntimeMessage<RuntimeStatus>({ type: "GET_STATUS" })
      .then(setStatus)
      .catch(() => undefined);

    const listener = (message: StatusUpdateMessage) => {
      if (message.type === "STATUS_UPDATE") {
        setStatus(message.status);
      }
    };
    chrome.runtime.onMessage.addListener(listener);
    return () => chrome.runtime.onMessage.removeListener(listener);
  }, []);

  return status;
}

