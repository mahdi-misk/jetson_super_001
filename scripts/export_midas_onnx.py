import torch
import os

def export_midas():
    print("Loading MiDaS_small model...")
    # Force CPU for export since Jetson CUDA PyTorch is broken
    device = torch.device("cpu")
    midas = torch.hub.load("intel-isl/MiDaS", "MiDaS_small", trust_repo=True)
    midas.to(device)
    midas.eval()

    dummy_input = torch.randn(1, 3, 384, 384).to(device)
    output_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models", "midas", "midas_small.onnx")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    print(f"Exporting MiDaS to {output_path}...")
    torch.onnx.export(
        midas,
        dummy_input,
        output_path,
        opset_version=12,
        input_names=['input'],
        output_names=['output'],
        dynamic_axes={'input': {0: 'batch_size'}, 'output': {0: 'batch_size'}}
    )
    print("Export complete!")

if __name__ == "__main__":
    export_midas()
