import os
import torch

def setup_offline_midas():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cache_dir = os.path.join(base_dir, "models", "torch_hub_cache")
    
    print(f"Setting local Torch Hub cache directory to: {cache_dir}")
    os.makedirs(cache_dir, exist_ok=True)
    torch.hub.set_dir(cache_dir)
    
    print("Downloading MiDaS architecture and weights from intel-isl/MiDaS...")
    print("You MUST have internet connection for this step!")
    
    try:
        # Load the model to force download and cache
        midas = torch.hub.load("intel-isl/MiDaS", "MiDaS_small", trust_repo=True)
        # Load the transforms to force download and cache
        midas_transforms = torch.hub.load("intel-isl/MiDaS", "transforms", trust_repo=True)
        
        print("\n✅ MiDaS successfully downloaded and cached locally!")
        print("Your system can now run 100% offline without connecting to GitHub.")
    except Exception as e:
        print(f"\n❌ Error downloading MiDaS: {e}")
        print("Make sure you are connected to the internet and try again.")

if __name__ == "__main__":
    setup_offline_midas()
