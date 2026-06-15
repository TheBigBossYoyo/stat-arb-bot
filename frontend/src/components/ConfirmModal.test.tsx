import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ConfirmModal from "./ConfirmModal";

function renderModal(onConfirm = vi.fn()) {
  render(
    <ConfirmModal
      open
      title="Send demo orders"
      description="Trading 212 demo only — live remains blocked."
      phrase="SEND DEMO ORDERS"
      mode="demo_execute"
      onConfirm={onConfirm}
      onClose={() => {}}
    />,
  );
  return { onConfirm };
}

describe("ConfirmModal (exact-phrase gate)", () => {
  it("keeps Confirm disabled until the EXACT phrase is typed", async () => {
    const { onConfirm } = renderModal();
    const confirm = screen.getByRole("button", { name: /confirm/i });
    const input = screen.getByRole("textbox", { name: /to confirm/i });

    expect(confirm).toBeDisabled();

    await userEvent.type(input, "send demo orders"); // wrong case
    expect(confirm).toBeDisabled();

    await userEvent.clear(input);
    await userEvent.type(input, "SEND DEMO ORDERS");
    expect(confirm).toBeEnabled();

    await userEvent.click(confirm);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("renders nothing when closed", () => {
    const onConfirm = vi.fn();
    const { container } = render(
      <ConfirmModal open={false} title="t" description="d" phrase="X" mode="paper"
        onConfirm={onConfirm} onClose={() => {}} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
