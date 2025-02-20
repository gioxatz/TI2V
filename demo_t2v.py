# Copyright (c) 2024 Mitsubishi Electric Research Laboratories (MERL)
# Copyright (C) 2023 NEC Laboratories America, Inc. ("NECLA"). All rights reserved.
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-License-Identifier: BSD-2-Clause
#
# Code adapted from https://github.com/nihaomiao/CVPR23_LFDM/tree/main/demo -- BSD-2-Clause License

# Demo for TI2V-Zero

# Downnload the code from TI2V-Zero official repo and save this file on the same folder and run it

import os
from copy import deepcopy

import imageio
import numpy as np
import torch
from PIL import Image

from modelscope_t2v_pipeline import TextToVideoSynthesisPipeline, tensor2vid
from diffusers import FluxPipeline
from diffusers import StableDiffusionPipeline, DPMSolverMultistepScheduler

from util import center_crop


def preprocess_vid(vid):
        vid_tensor = torch.from_numpy(vid / 255.0).type(torch.float32)
        vid_tensor = vid_tensor.unsqueeze(dim=0)
        vid_tensor = vid_tensor.permute(0, 4, 1, 2, 3)  # ncfhw
        # normalization
        mean = [0.5, 0.5, 0.5]
        std = [0.5, 0.5, 0.5]
        mean = torch.tensor(mean, device=vid_tensor.device).reshape(1, -1, 1, 1, 1)  # ncfhw
        std = torch.tensor(std, device=vid_tensor.device).reshape(1, -1, 1, 1, 1)  # ncfhw
        vid_tensor = vid_tensor.sub_(mean).div_(std)
        return vid_tensor

print(torch.cuda.is_available())
print("Num GPUs available: ", torch.cuda.device_count())



model_id = "stabilityai/stable-diffusion-2-1"

imagepr = input("Give me the prompt for the image\n")

# Use the DPMSolverMultistepScheduler (DPM-Solver++) scheduler here instead
pipe = StableDiffusionPipeline.from_pretrained(model_id, torch_dtype=torch.float16)
pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config)
pipe = pipe.to("cuda")

image = pipe(imagepr).images[0]
    

image.save("genimage.png")

input = input("Give me the prompt for the video\n")


# After running initialization.py, set the config path to your ModelScope path
config = {"model": "./weights", "device": "gpu"}

# Set your output path
output_dir = "./example-video"
output_img_dir = "./example-image"
os.makedirs(output_dir, exist_ok=True)
os.makedirs(output_img_dir, exist_ok=True)

# Set parameters for temporal resampling and DDIM
resample_iter = 2
# ddim_step = 10
ddim_step = 10

# Set the number of new frames
NUM_NEW_FRAMES = 15
print("#new_frame:", NUM_NEW_FRAMES)

# Set the number of generated videos
NUM_SAMPLES = 1

img_path = "genimage.png"

postfix = "-resample%02d-s%02d-mean%04d" % (resample_iter, ddim_step, np.random.randint(low=0, high=10000))
add_vid_cond = True
use_ddpm_inversion = True
print(img_path)
print(input, postfix)
print("video_cond:", add_vid_cond, "ddpm_inv:", use_ddpm_inversion, "#resample:", resample_iter)

# default parameters
IMG_H = 256
IMG_W = 256
NUM_FRAMES = 16
NUM_COND_FRAMES = 15

# read image
first_img_npy = imageio.v2.imread(img_path)
# crop image
first_img_npy = center_crop(first_img_npy)
# resize image
first_img_npy = np.asarray(Image.fromarray(first_img_npy).resize((IMG_H, IMG_W)))
# repeat image
first_img_npy_list = [first_img_npy for i in range(NUM_COND_FRAMES)]
cond_vid_npy = np.stack(first_img_npy_list, axis=0)
t2v_pipeline = TextToVideoSynthesisPipeline(**config)
processed_input = t2v_pipeline.preprocess([input])



for sample_idx in range(NUM_SAMPLES):
    newpostfix = postfix + "-%02d" % sample_idx
    vid_tensor = t2v_pipeline.preprocess_vid(deepcopy(cond_vid_npy))
    new_output_tensor = vid_tensor.clone().detach().cpu()
    output_filename = input.replace(" ", "_")[:-1] + "%s-%02d.gif" % (newpostfix, NUM_NEW_FRAMES)
    video_name = os.path.basename(output_filename)[:-4]
    save_img_dir = os.path.join(output_img_dir, video_name)
    os.makedirs(save_img_dir, exist_ok=True)
    img_name = video_name + "%03d.jpg" % 0
    img_path = os.path.join(save_img_dir, img_name)
    imageio.v2.imsave(img_path, first_img_npy)

    # image-to-video generation
    for i in range(NUM_NEW_FRAMES):
        print("i:", i, input, newpostfix)
        output = t2v_pipeline.forward_with_vid_resample(
            processed_input,
            vid=vid_tensor,
            add_vid_cond=add_vid_cond,
            use_ddpm_inversion=use_ddpm_inversion,
            resample_iter=resample_iter,
            ddim_step=ddim_step,
            guide_scale=9.0,
        )
        with torch.no_grad():
            new_frame = t2v_pipeline.model.autoencoder.decode(output[:, :, -1].cuda())
        print("shape", new_frame.shape)
        new_frame = new_frame.data.cpu().unsqueeze(dim=2)
        img_npy = tensor2vid(new_frame.clone().detach())[0]
        img_name = video_name + "%03d.jpg" % (i + 1)
        img_path = os.path.join(save_img_dir, img_name)
        imageio.v2.imsave(img_path, img_npy)
        new_output_tensor = torch.cat((new_output_tensor, new_frame), dim=2)
        vid_tensor = new_output_tensor[:, :, (i + 1) :]
        assert vid_tensor.size(2) == NUM_COND_FRAMES
    output_video = t2v_pipeline.postprocess(
        new_output_tensor[:, :, (NUM_COND_FRAMES - 1) :], os.path.join(output_dir, output_filename)
    )
    print("saving to", save_img_dir)
    print("saving video to", os.path.join(output_dir, output_filename))
