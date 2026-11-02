import React, { useRef } from "react";
import { TextInput, type TextInputProps } from "react-native";
import { createTextInputSync } from "../domain/text-input-sync";

type Props = Omit<TextInputProps, "value" | "defaultValue" | "onChangeText"> & {
  value: string;
  onChangeText: (text: string) => void;
};

// A TextInput that owns its native text while the user types and only takes
// the parent's value for a genuine programmatic change; see text-input-sync.
export function StableTextInput({ value, onChangeText, ...props }: Props) {
  const sync = useRef<ReturnType<typeof createTextInputSync>>(undefined);
  sync.current ??= createTextInputSync(value);
  const seed = sync.current.render(value);
  return (
    <TextInput
      {...props}
      key={seed.generation}
      defaultValue={seed.text}
      onChangeText={(text) => {
        sync.current?.typed(text);
        onChangeText(text);
      }}
    />
  );
}
