export type ButtonProps = {
  label: string;
  onPress: () => void;
  disabled?: boolean;
  secondary?: boolean;
  testID?: string;
};
export type SegmentsProps = {
  label: string;
  options: { value: string; label: string; testID?: string }[];
  value: string;
  onChange: (value: string) => void;
};
