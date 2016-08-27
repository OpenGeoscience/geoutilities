import glob
import os
import shutil
from xml.etree.ElementTree import parse, SubElement

import click
import gdal


DIRECTORY = os.path.dirname(os.path.realpath(__file__))


def list_files(directory, extension):
    """
    Lists all the files in a given directory with a wildcard

    :param directory: Directory to be checked
    :param extension: File extension to be searched
    :return: List of files matching the extension
    """

    return glob.glob(os.path.join(directory, '*.{}'.format(extension)))


def create_output_directory(hdf):
    """
    Creates a unique output directory to store the intermediate vrt files

    :param hdf: HDF file to be processed
    :return: Folder
    """

    direc = os.path.splitext(hdf)[0]
    if not os.path.exists(direc):
        os.makedirs(direc)

    return direc


def get_metadata_item(subdataset, keyword):
    """
    Checks for keyword in metadata and returns if it exists

    :param subdataset: HDF subdataset
    :param keyword: Keyword to
    :return: Metadata item
    """

    dataset = gdal.Open(subdataset, gdal.GA_ReadOnly)

    metadata = dataset.GetMetadata_Dict()

    # Filter the metadata
    filtered_meta = {k: v for k, v in metadata.iteritems()
                     if keyword in k.lower()}

    # Hopefully there will be one element in the dictionary
    return filtered_meta[filtered_meta.keys()[0]]



def modify_vrt(vrt, scale):
    """
    Makes modifications to the vrt file to fix the values.

    :param vrt: VRT file to be processed
    :param scale: Scale value from get_metadata_item function
    :return: None
    """

    doc = parse(vrt)

    root = doc.getroot()

    # Fix the datatype if it is wrong
    raster_band = root.find('VRTRasterBand')
    raster_band.set('dataType', 'Float32')

    # Add the scale to the vrt file
    source = root.find('VRTRasterBand').find('ComplexSource')
    scale_ratio = SubElement(source, 'ScaleRatio')
    scale_ratio.text = scale

    # Write the scale input
    # vrt files are overwritten with the same name
    doc.write(vrt, xml_declaration=True)


def convert_to_vrt(subdatasets, data_dir, bands):
    """
    Loops through the subdatasets and creates vrt files

    :param subdatasets: Subdataset of every HDF file
    :param data_dir: Result of create_output_directory method
    :return: None
    """

    if bands:
        bands = [int(str(b)) for b in bands]
        subdatasets_dict = dict((key,value) for key, value in enumerate(subdatasets, start=1)
                           if key in bands)
        for order, band in enumerate(bands, start=1):
            output_name = os.path.join(
                data_dir,
                "{}_Band{}_{}.vrt".format(
                    str(order).zfill(2),
                    str(band).zfill(2),
                    subdatasets_dict[band][0].split(":")[-1]))
                    # Create the virtual raster

            gdal.BuildVRT(output_name, subdatasets_dict[band][0])

            # Check if scale and offset exists
            scale = get_metadata_item(subdatasets_dict[band][0], 'scale')

            modify_vrt(output_name, scale)          
    else:
        subdatasets_dict = dict(enumerate(subdatasets, start=1))
        for order, band in subdatasets_dict.items():
            output_name = os.path.join(
                data_dir,
                "Band{}_{}.vrt".format(
                    str(order).zfill(2),
                    subdatasets_dict[order][0]))

            gdal.BuildVRT(output_name, subdatasets_dict[order][0])

            scale = get_metadata_item(subdatasets_dict[order][0], 'scale')

            modify_vrt(output_name, scale)
    
def clear_temp_files(data_dir, vrt_output):
    """ Removes the temporary files """

    os.remove(vrt_output)
    shutil.rmtree(data_dir)


def hdf2tif(hdf, overwrite, bands, reproject=True):
    """
    Converts hdf files to tiff files

    :param hdf: HDF file to be processed
    :param reproject: Will be reprojected by default
    :return: None
    """

    if overwrite:
        try:
            os.remove(list_files(DIRECTORY, 'tif')[0])
        except IndexError:
            pass
        
    dataset = gdal.Open(hdf, gdal.GA_ReadOnly)
    subdatasets = dataset.GetSubDatasets()
    data_dir = create_output_directory(hdf)
    convert_to_vrt(subdatasets, data_dir, bands)
    vrt_options = gdal.BuildVRTOptions(separate=True)
    vrt_list = list_files(data_dir, 'vrt')
    vrt_output = hdf.replace('.hdf', '.vrt')
    gdal.BuildVRT(vrt_output, sorted(vrt_list), options=vrt_options)
    if reproject:
        proj = "+proj=sinu +R=6371007.181 +nadgrids=@null +wktext"
        warp_options = gdal.WarpOptions(srcSRS=proj, dstSRS="EPSG:4326",
                                        warpMemoryLimit="4096",
                                        multithread=True)
    else:
        warp_options = ""
    output_tiff = vrt_output.replace(".vrt", ".tif")

    if not os.path.exists(output_tiff):
        gdal.Warp(output_tiff,
              vrt_output, options=warp_options)

    metadata = []
    
    # Add the metadata
    for index, subd in enumerate(subdatasets):
        # Generate band names
        band_name = "{}:{}".format(str(index + 1).zfill(2),
                                          subd[0].split(":")[4])
        metadata.append(band_name)

    # Inject the metadata to the tiff
    gdal.Open(output_tiff).SetMetadata(str(metadata))

    clear_temp_files(data_dir, vrt_output)

    return output_tiff

@click.command()
@click.argument('hdf_file')
@click.argument('bands', nargs=-1)
@click.option('--overwrite', default=True, help="Overwrite the created tiff")
def main(hdf_file, overwrite, bands):
    """ Main function which orchestrates the conversion """

    hdf2tif(hdf_file, overwrite, bands)

if __name__ == "__main__":
    main()
