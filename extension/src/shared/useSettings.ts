import * as React from "react";

import type { UiSettings } from "./messages";
import { DEFAULT_SETTINGS } from "./messages";
import { sendRuntimeMessage } from "./chrome";

export function useSettings() {
  const [settings, setSettings] = React.useState<UiSettings>(DEFAULT_SETTINGS);

  React.useEffect(() => {
    sendRuntimeMessage<UiSettings>({ type: "GET_SETTINGS" }).then(setSettings).catch(() => undefined);
  }, []);

  async function updateSettings(update: Partial<UiSettings>): Promise<void> {
    const next = await sendRuntimeMessage<UiSettings>({ type: "SAVE_SETTINGS", settings: update });
    setSettings(next);
  }

  return { settings, updateSettings };
}

