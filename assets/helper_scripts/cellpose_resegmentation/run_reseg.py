#!/usr/bin/env python3
"""
napari_patch_resegment.py

Interactive tool for creating patches from mIHC images and editing segmentation masks.
Built-in patch creation widget - no external plugins required.
"""

import os
import tkinter as tk
from tkinter import ttk, filedialog
import napari
from napari.layers import Shapes
from pathlib import Path
import tifffile
import numpy as np
from tifffile import TiffFile
import xml.etree.ElementTree as ET
from datetime import datetime
from magicgui import magicgui
from magicgui.widgets import Container, Label, PushButton, ComboBox, SpinBox, FileEdit
import subprocess
import sys


PROMPT_TEXT = "Please enter the path to your results directory"


class DirEntryDialog(tk.Toplevel):
    def __init__(self, parent, title="Napari Patch Resegmenter", initialdir=None):
        super().__init__(parent)
        self.parent = parent
        self.initialdir = initialdir or os.getcwd()
        self.result = None

        self.title(title)
        self.resizable(False, False)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        self._build_widgets()
        self.geometry("+%d+%d" % (parent.winfo_rootx() + 50, parent.winfo_rooty() + 50))
        self.entry.focus_set()
        self.wait_window()

    def _build_widgets(self):
        pad = dict(padx=10, pady=8)

        lbl = ttk.Label(self, text=PROMPT_TEXT)
        lbl.grid(row=0, column=0, columnspan=3, sticky="w", **pad)

        self.entry_var = tk.StringVar(value=self.initialdir)
        self.entry = ttk.Entry(self, textvariable=self.entry_var, width=60)
        self.entry.grid(row=1, column=0, columnspan=2, sticky="we", padx=10)

        browse_btn = ttk.Button(self, text="Browse...", command=self._on_browse)
        browse_btn.grid(row=1, column=2, sticky="e", padx=(0,10))

        ok_btn = ttk.Button(self, text="OK", command=self._on_ok)
        ok_btn.grid(row=2, column=1, sticky="e", pady=(0,10), padx=(0,5))

        cancel_btn = ttk.Button(self, text="Cancel", command=self._on_cancel)
        cancel_btn.grid(row=2, column=2, sticky="w", pady=(0,10), padx=(5,10))

    def _on_browse(self):
        path = filedialog.askdirectory(parent=self, initialdir=self.initialdir, title="Select Results Directory")
        if path:
            self.entry_var.set(path)

    def _on_ok(self):
        path = self.entry_var.get().strip()
        if path:
            self.result = os.path.abspath(path)
        else:
            self.result = None
        self.destroy()

    def _on_cancel(self):
        self.result = None
        self.destroy()


def get_results_dir(initialdir=None):
    """Show modal dialog for results directory selection."""
    try:
        root = tk.Tk()
        root.withdraw()
        dialog = DirEntryDialog(root, initialdir=initialdir)
        root.destroy()
        return dialog.result
    except tk.TclError:
        return None


def find_files(root_path):
    """
    Locate image, segmentation, and DAPI files in results directory.
    
    Returns:
        tuple: (image_path, seg_path, dapi_path, original_image_path)
    """
    root = Path(root_path)
    
    file_path = None
    seg_file_path = None
    dapi_processed = None
    original_image_path = None
    
    if not root.is_dir():
        return None, None, None, None
    
    # Extract sample name from directory
    sample_name = root.name
    
    # Find downscaled image in image_downscale/
    downscale_dir = root / "image_downscale"
    if downscale_dir.exists():
        downscaled = downscale_dir / f"{sample_name}.downscaled.ome.tiff"
        if downscaled.is_file():
            file_path = str(downscaled)
            print(f"Found downscaled image: {file_path}")
    
    # Find original high-res image in image_hires/
    hires_dir = root / "image_hires"
    if hires_dir.exists():
        original = hires_dir / f"{sample_name}.ome.tif"
        if original.is_file():
            original_image_path = str(original)
            print(f"Found original image: {original_image_path}")
    
    # Find cellpose segmentation in segmentation/
    seg_dir = root / "segmentation"
    if seg_dir.exists():
        cellpose_mask = seg_dir / f"{sample_name}_cellpose.tif"
        if cellpose_mask.is_file():
            seg_file_path = str(cellpose_mask)
            print(f"Found cellpose segmentation: {seg_file_path}")
    
    # Find DAPI processed in dapi_processed/
    dapi_dir = root / "dapi_processed"
    if dapi_dir.exists():
        dapi_file = dapi_dir / f"{sample_name}_dapi_processed.tif"
        if dapi_file.is_file():
            dapi_processed = str(dapi_file)
            print(f"Found dapi_processed: {dapi_processed}")
    
    return file_path, seg_file_path, dapi_processed, original_image_path


def extract_channel_info(tif):
    """
    Extract channel names and axes from OME-TIFF.
    
    Returns:
        tuple: (channel_names, axes, c_idx, n_channels)
    """
    series = tif.series[0]
    axes = series.axes
    ome = tif.ome_metadata
    
    channel_names = []
    if ome:
        try:
            root = ET.fromstring(ome)
            channel_elems = root.findall('.//{*}Channel')
            channel_names = [ch.get('Name') or ch.get('ID') or '' for ch in channel_elems]
        except ET.ParseError:
            pass

    if 'C' in axes:
        c_idx = axes.index('C')
        n_channels = series.shape[c_idx]
    elif series.ndim >= 3:
        c_idx = 0
        n_channels = series.shape[0]
    else:
        c_idx = None
        n_channels = 1

    return channel_names, axes, c_idx, n_channels


def setup_viewer(image, seg_image, channel_names, c_idx, n_channels, dapi_processed=None):
    """
    Create napari viewer with image and segmentation layers.
    
    Returns:
        napari.Viewer instance
    """
    viewer = napari.Viewer()
    
    if c_idx is None:
        name = channel_names[0] if channel_names else "Image"
        viewer.add_image(image, name=name, visible=False)
    else:
        colors = ['red', 'green', 'blue', 'yellow', 'magenta', 'cyan', 'white', 'orange', 'purple']
        for i in range(n_channels):
            ch_arr = np.take(image, indices=i, axis=c_idx)
            name = channel_names[i] if i < len(channel_names) and channel_names[i] else f"Channel-{i}"
            
            # Force DAPI to blue, others start hidden
            is_dapi = 'DAPI' in name.upper()
            color = 'blue' if is_dapi else (colors[i % len(colors)] if n_channels < 10 else None)
            visible = is_dapi
            blending = 'additive' if n_channels < 10 else 'translucent'
            gamma = 0.75 if n_channels < 10 else 1.0
            
            viewer.add_image(ch_arr, name=name, colormap=color, blending=blending, 
                           gamma=gamma, visible=visible)
            
            p_max = np.max(ch_arr)
            p_min = 0.02 * p_max
            p_max = 0.75 * p_max
            if p_min >= p_max:
                p_max = p_min + 1
            viewer.layers[-1].contrast_limits = (p_min, p_max)
    
    # Move DAPI to bottom
    dapi_layer_idx = next((i for i, layer in enumerate(viewer.layers) if 'DAPI' in layer.name.upper()), None)
    if dapi_layer_idx is not None:
        viewer.layers.move(dapi_layer_idx, len(viewer.layers) - 1)
    
    if dapi_processed:
        try:
            dapi_img = tifffile.imread(dapi_processed)
            viewer.add_image(dapi_img, name="DAPI (Pre-processed)", colormap='gray', 
                           blending='translucent', visible=True)
            # Move to bottom
            viewer.layers.move(-1, len(viewer.layers) - 1)
        except Exception:
            pass
    
    viewer.add_labels(seg_image, name="Segmentation (Original)", visible=True)
    
    # Add empty layer for corrections
    empty_seg = np.zeros_like(seg_image)
    viewer.add_labels(empty_seg, name="Segmentation (Corrections)", visible=True)
    
    return viewer


class PatchManager:
    """Manages patch extraction and saving."""
    
    def __init__(self, viewer, original_image_path, output_base_dir):
        self.viewer = viewer
        self.original_image_path = original_image_path
        self.output_base_dir = Path(output_base_dir)
        self.patches_layer = None
        self.last_save_dir = None
        
        # Load full resolution image metadata
        with TiffFile(original_image_path) as tif:
            series = tif.series[0]
            self.full_shape = series.shape
            self.axes = series.axes
            self.c_idx = self.axes.index('C') if 'C' in self.axes else 0
        
        # Create patches shapes layer
        self._init_patches_layer()
    
    def _init_patches_layer(self):
        """Initialize or get the patches shapes layer."""
        for layer in self.viewer.layers:
            if isinstance(layer, Shapes) and layer.name == "Patches":
                self.patches_layer = layer
                return
        
        self.patches_layer = self.viewer.add_shapes(
            name="Patches",
            edge_color='cyan',
            edge_width=3,
            face_color='transparent',
            shape_type='rectangle'
        )
    
    def add_patch_at_current_view(self, patch_size=128):
        """Add a patch rectangle at the current viewer center."""
        # Get current view center
        camera_center = self.viewer.camera.center[-2:]  # Get Y, X
        
        y_center, x_center = camera_center
        half_size = patch_size // 2
        
        # Get image dimensions from any visible layer
        ref_layer = None
        for layer in self.viewer.layers:
            if hasattr(layer, 'data') and layer.data.ndim == 2:
                ref_layer = layer
                break
        
        if ref_layer is None:
            print("Error: No reference layer found for patch bounds")
            return
        
        # Create rectangle coordinates
        y_min = max(0, int(y_center - half_size))
        x_min = max(0, int(x_center - half_size))
        y_max = min(ref_layer.data.shape[0], y_min + patch_size)
        x_max = min(ref_layer.data.shape[1], x_min + patch_size)
        
        rectangle = np.array([
            [y_min, x_min],
            [y_min, x_max],
            [y_max, x_max],
            [y_max, x_min]
        ])
        
        self.patches_layer.add_rectangles(rectangle)
        print(f"Added patch at ({y_min}:{y_max}, {x_min}:{x_max})")
    
    def save_patches(self, save_npy=False):
        """Save all defined patches in Cellpose format."""
        if len(self.patches_layer.data) == 0:
            print("No patches to save.")
            return
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = self.output_base_dir / "patches" / timestamp
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Load full resolution image
        with TiffFile(self.original_image_path) as tif:
            full_image = tif.series[0].asarray()
        
        # Get DAPI layer for patches (prefer pre-processed)
        dapi_layer = None
        for layer in self.viewer.layers:
            if layer.name == "DAPI (Pre-processed)":
                dapi_layer = layer
                break
            elif 'DAPI' in layer.name.upper() and dapi_layer is None:
                dapi_layer = layer
        
        if dapi_layer is None:
            print("Error: No DAPI layer found.")
            return
        
        dapi_data = dapi_layer.data
        
        # Get segmentation layers - merge original + corrections
        seg_original = self.viewer.layers['Segmentation (Original)'].data
        seg_corrections = self.viewer.layers['Segmentation (Corrections)'].data
        
        # Merge: corrections override original where non-zero
        seg_merged = seg_original.copy()
        seg_merged[seg_corrections > 0] = seg_corrections[seg_corrections > 0]
        
        # Save patch coordinates to JSON for later loading
        patch_coords_data = {
            'timestamp': timestamp,
            'patches': []
        }
        
        saved_count = 0
        for idx, patch_coords in enumerate(self.patches_layer.data):
            coords = np.array(patch_coords)
            y_min, y_max = int(coords[:, 0].min()), int(coords[:, 0].max())
            x_min, x_max = int(coords[:, 1].min()), int(coords[:, 1].max())
            
            # Validate bounds
            if y_min >= y_max or x_min >= x_max:
                print(f"Skipping invalid patch {idx}: zero size")
                continue
            
            # Extract DAPI patch (always 2D single channel for Cellpose)
            dapi_patch = dapi_data[y_min:y_max, x_min:x_max]
            
            # Extract segmentation patch
            seg_patch = seg_merged[y_min:y_max, x_min:x_max]
            
            # Validate patches are non-empty
            if dapi_patch.size == 0 or seg_patch.size == 0:
                print(f"Skipping patch {idx}: zero-size array")
                continue
            
            base_name = f"patch_{idx:03d}_{timestamp}"
            
            if save_npy:
                img_path = output_dir / f"{base_name}_img.npy"
                mask_path = output_dir / f"{base_name}_masks.npy"
                np.save(img_path, dapi_patch.astype(np.float32))
                np.save(mask_path, seg_patch.astype(np.uint16))
            else:
                img_path = output_dir / f"{base_name}_img.tif"
                mask_path = output_dir / f"{base_name}_masks.tif"
                
                tifffile.imwrite(img_path, dapi_patch.astype(np.float32))
                tifffile.imwrite(mask_path, seg_patch.astype(np.uint16))
            
            # Store coordinates for reload
            patch_coords_data['patches'].append({
                'index': idx,
                'coords': coords.tolist(),
                'bounds': {'y_min': y_min, 'y_max': y_max, 'x_min': x_min, 'x_max': x_max}
            })
            
            saved_count += 1
            print(f"Saved patch {idx}: {img_path.name}, {mask_path.name}")
        
        # Save patch metadata
        import json
        metadata_path = output_dir / "patch_metadata.json"
        with open(metadata_path, 'w') as f:
            json.dump(patch_coords_data, f, indent=2)
        
        self.last_save_dir = output_dir
        print(f"\n✓ Saved {saved_count} patches to {output_dir}")
        print(f"Ready for Cellpose training")
        
        return output_dir
    
    def load_patches(self, patch_dir):
        """Load previously saved patches and add to viewer."""
        import json
        
        patch_dir = Path(patch_dir)
        metadata_path = patch_dir / "patch_metadata.json"
        
        if not metadata_path.exists():
            print(f"No patch metadata found at {metadata_path}")
            return
        
        with open(metadata_path, 'r') as f:
            patch_data = json.load(f)
        
        # Clear existing patches
        self.patches_layer.data = []
        
        # Reload patch rectangles
        for patch_info in patch_data['patches']:
            coords = np.array(patch_info['coords'])
            self.patches_layer.add_rectangles(coords)
        
        print(f"Loaded {len(patch_data['patches'])} patches from {patch_dir.name}")
        
        # Load segmentation corrections if they exist
        corrections_layer = self.viewer.layers['Segmentation (Corrections)']
        
        # Try to reconstruct corrections from saved masks
        timestamp = patch_data['timestamp']
        for patch_info in patch_data['patches']:
            idx = patch_info['index']
            bounds = patch_info['bounds']
            
            mask_path = patch_dir / f"patch_{idx:03d}_{timestamp}_masks.tif"
            if mask_path.exists():
                mask_patch = tifffile.imread(mask_path)
                
                # Insert back into corrections layer at original position
                y_min, y_max = bounds['y_min'], bounds['y_max']
                x_min, x_max = bounds['x_min'], bounds['x_max']
                
                # Only apply non-zero corrections
                patch_region = corrections_layer.data[y_min:y_max, x_min:x_max]
                patch_region[mask_patch > 0] = mask_patch[mask_patch > 0]
        
        print("Loaded patch corrections into Segmentation (Corrections) layer")


def create_workflow_widget(patch_manager, output_base_dir):
    """Create comprehensive workflow widget with all steps."""
    
    container = Container()
    
    # === STEP 1: PATCH CREATION ===
    container.append(Label(value="<h3>Step 1: Patch Creation</h3>"))
    container.append(Label(value="Navigate to regions of interest and create patches"))
    
    patch_size_widget = SpinBox(value=128, min=64, max=2048, step=64, label="Patch size (px)")
    
    def add_patch_callback():
        patch_manager.add_patch_at_current_view(patch_size_widget.value)
    
    add_patch_btn = PushButton(text="Add Patch at View Center")
    add_patch_btn.changed.connect(add_patch_callback)
    
    container.append(patch_size_widget)
    container.append(add_patch_btn)
    
    # Add load patches button
    load_status = Label(value="")
    
    def load_patches_callback():
        try:
            root = tk.Tk()
            root.withdraw()
            patches_base = Path(output_base_dir) / "patches"
            patches_base.mkdir(exist_ok=True)
            
            patch_dir = filedialog.askdirectory(
                title="Select saved patch directory to load",
                initialdir=str(patches_base)
            )
            root.destroy()
            
            if patch_dir:
                patch_manager.load_patches(patch_dir)
                load_status.value = f"✓ Loaded patches from {Path(patch_dir).name}"
            else:
                load_status.value = "Load cancelled"
        except Exception as e:
            load_status.value = f"✗ Error loading: {str(e)}"
    
    load_patches_btn = PushButton(text="Load Previous Patches")
    load_patches_btn.changed.connect(load_patches_callback)
    
    container.append(load_patches_btn)
    container.append(load_status)
    container.append(Label(value="Tip: Use rectangle select tool to move/resize patches"))
    container.append(Label(value="---"))
    
    # === STEP 2: RESEGMENTATION ===
    container.append(Label(value="<h3>Step 2: Resegmentation</h3>"))
    container.append(Label(value="Edit segmentation in 'Segmentation (Corrections)' layer"))
    container.append(Label(value="• Select the Corrections layer in layer list"))
    container.append(Label(value="• Use paint brush to add cells (start from label 1)"))
    container.append(Label(value="• Use eraser to remove cells"))
    container.append(Label(value="• Press '=' or '+' to advance to next label"))
    container.append(Label(value="• Press '-' to go back to previous label"))
    container.append(Label(value="• Press 'p' to pick existing label"))
    container.append(Label(value="• Ctrl+Z to undo"))
    container.append(Label(value="---"))
    
    # === STEP 3: PATCH SAVING ===
    container.append(Label(value="<h3>Step 3: Save Patches</h3>"))
    container.append(Label(value="Save patches with corrected segmentation"))
    
    save_status = Label(value="No patches saved yet")
    
    def save_patches_callback():
        output_dir = patch_manager.save_patches()
        if output_dir:
            save_status.value = f"✓ Saved to: {output_dir.name}"
    
    save_patches_btn = PushButton(text="Save All Patches (Cellpose Format)")
    save_patches_btn.changed.connect(save_patches_callback)
    
    container.append(save_patches_btn)
    container.append(save_status)
    container.append(Label(value="---"))
    
    # === STEP 4: MODEL SELECTION ===
    container.append(Label(value="<h3>Step 4: Model Selection</h3>"))
    container.append(Label(value="Select base Cellpose model for retraining"))
    
    model_choices = ['cyto', 'cyto2', 'cyto3', 'nuclei', 'tissuenet_cp3', 'livecell_cp3', 'Custom...']
    model_select = ComboBox(choices=model_choices, value='cyto3', label="Base model")
    
    custom_model_path = FileEdit(mode='r', label="Custom model path", visible=False)
    
    def on_model_change():
        custom_model_path.visible = (model_select.value == 'Custom...')
    
    model_select.changed.connect(on_model_change)
    
    container.append(model_select)
    container.append(custom_model_path)
    container.append(Label(value="---"))
    
    # === STEP 5: RETRAINING ===
    container.append(Label(value="<h3>Step 5: Model Retraining</h3>"))
    container.append(Label(value="Retrain Cellpose model on your corrected patches"))
    
    training_status = Label(value="Ready to train")
    
    def retrain_callback():
        # Select training directory
        try:
            root = tk.Tk()
            root.withdraw()
            patches_base = Path(output_base_dir) / "patches"
            patches_base.mkdir(exist_ok=True)
            
            train_dir = filedialog.askdirectory(
                title="Select patch directory for training",
                initialdir=str(patches_base)
            )
            root.destroy()
            
            if not train_dir:
                training_status.value = "Training cancelled"
                return
            
            # Get model name
            if model_select.value == 'Custom...':
                model_name = str(custom_model_path.value)
                if not model_name or not Path(model_name).exists():
                    training_status.value = "Error: Invalid custom model path"
                    return
            else:
                model_name = model_select.value
            
            training_status.value = f"Training on {Path(train_dir).name}..."
            print(f"\n=== Starting Cellpose Training ===")
            print(f"Training directory: {train_dir}")
            print(f"Base model: {model_name}")
            
            # Build cellpose command
            cmd = [
                sys.executable, "-m", "cellpose",
                "--train",
                "--dir", train_dir,
                "--pretrained_model", model_name,
                "--mask_filter", "_masks",
                "--img_filter", "_img",
                "--chan", "0",
                "--chan2", "0",
                "--learning_rate", "0.1",
                "--n_epochs", "100",
                "--batch_size", "8",
                "--verbose"
            ]
            
            print(f"Command: {' '.join(cmd)}\n")
            
            # Run training
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1
            )
            
            # Stream output
            for line in process.stdout:
                print(line.rstrip())
            
            process.wait()
            
            if process.returncode == 0:
                training_status.value = "✓ Training completed successfully!"
                print("\n=== Training Complete ===")
            else:
                training_status.value = f"✗ Training failed (exit code {process.returncode})"
                print(f"\n=== Training Failed ===")
                
        except Exception as e:
            training_status.value = f"✗ Error: {str(e)}"
            print(f"Training error: {e}")
    
    retrain_btn = PushButton(text="Retrain Cellpose Model")
    retrain_btn.changed.connect(retrain_callback)
    
    container.append(retrain_btn)
    container.append(training_status)
    container.append(Label(value="Note: Training will open in console. Check terminal for progress."))
    
    return container


def main():
    """Main entry point."""
    path = get_results_dir()
    if not path:
        print("No directory selected.")
        return

    file_path, seg_file_path, dapi_processed, original_image_path = find_files(path)

    if not file_path:
        print("No .downscaled.ome.tiff file found.")
        return
    if not seg_file_path:
        print("No segmentation file found.")
        return
    if not original_image_path:
        print("No original OME-TIFF found for patch extraction.")
        return

    # Load data
    seg_image = tifffile.imread(seg_file_path)

    with TiffFile(file_path) as tif:
        image = tif.series[0].asarray()
        channel_names, axes, c_idx, n_channels = extract_channel_info(tif)

    # Create viewer
    viewer = setup_viewer(image, seg_image, channel_names, c_idx, n_channels, dapi_processed)

    # Initialize patch manager
    patch_manager = PatchManager(viewer, original_image_path, path)
    
    # Add comprehensive workflow widget
    workflow_widget = create_workflow_widget(patch_manager, path)
    viewer.window.add_dock_widget(workflow_widget, area='right', name='Cellpose Retraining Workflow')

    print("\n" + "="*60)
    print("CELLPOSE RETRAINING WORKFLOW")
    print("="*60)
    print("Follow the steps in the right sidebar:")
    print("1. Create patches at regions of interest")
    print("2. Edit segmentation in Corrections layer")
    print("3. Save patches in Cellpose format")
    print("4. Select base model for retraining")
    print("5. Retrain model on your corrected data")
    print("="*60 + "\n")

    napari.run()


if __name__ == "__main__":
    main()
