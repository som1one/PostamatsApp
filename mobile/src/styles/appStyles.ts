import { StyleSheet } from "react-native";

export { MAP_CARD_GAP, MAP_CARD_WIDTH, palette } from "./theme";

import { styleChunk1 } from "./chunks/styleChunk1";
import { styleChunk2 } from "./chunks/styleChunk2";
import { styleChunk3 } from "./chunks/styleChunk3";
import { styleChunk4 } from "./chunks/styleChunk4";
import { styleChunk5 } from "./chunks/styleChunk5";
import { styleChunk6 } from "./chunks/styleChunk6";

const styleDefinitions = {
  ...styleChunk1,
  ...styleChunk2,
  ...styleChunk3,
  ...styleChunk4,
  ...styleChunk5,
  ...styleChunk6,
};

export const styles = StyleSheet.create(styleDefinitions as any);
