
import os
import numpy as np
import math
import fiona
import shutil
from shapely.geometry import mapping, shape
import rasterio
from rasterio.tools.mask import mask
from pygeoprocessing import routing

from skimage import img_as_float
from skimage.feature import peak_local_max
from shapely.geometry import Point,Polygon,MultiPolygon
from shapely.ops import cascaded_union

def clip(input_dem,shp,buffersize,out_name):
        
    output_dem=os.path.dirname(input_dem)+'/'+out_name+'.tif'
    if os.path.basename(shp) == 'outlines.shp':
        geoms=[mapping(shape(outlines['geometry']).buffer(buffersize))]
    else:
        with fiona.open(shp, "r") as shapefile:
            geoms = [mapping(shape(shapefile.next()['geometry']).buffer(buffersize))]

    with rasterio.open(input_dem) as src:
        #out_image, out_transform = mask(src, geoms,nodata=np.nan, crop=False)
        out_image, out_transform = mask(src,geoms , nodata=np.nan, crop=False)
        out_meta = src.meta.copy()
    
    out_meta.update({"driver": "GTiff",
                     "height": out_image.shape[1],
                     "width": out_image.shape[2],
                     "nodata": np.nan,
                     "transform": out_transform})
    with rasterio.open(output_dem, "w", **out_meta) as dest:
        dest.write(out_image)
    return output_dem

def compactness(polygon):
    coord=np.array(polygon.exterior.coords)
    #calculate max distance(perimeter)
    max_dist=Point(coord[np.argmin(coord[:,1])]).distance(Point(coord[np.argmax(coord[:,1])]))
    x_dist=Point(coord[np.argmin(coord[:,0])]).distance(Point(coord[np.argmax(coord[:,0])]))
    if x_dist>max_dist:
        max_dist=x_dist
    if max_dist*math.pi/polygon.boundary.length > 0.5:
        return True
    else:
        return False
def flowacc(input_dem):
        
    new_flow_direction_map_uri =os.path.dirname(input_dem)+'/flow_dir.tif'
    new_flow_map_accumulation_uri = os.path.dirname(input_dem)+'/flow_accumulation.tif'   
    #calculate flow direction
    routing.flow_direction_d_inf(input_dem, new_flow_direction_map_uri)
    #calculate flow_accumulation
    routing.flow_accumulation(new_flow_direction_map_uri,input_dem, new_flow_map_accumulation_uri)
    clip(new_flow_map_accumulation_uri, os.path.dirname(input_dem)+'/gutter.shp', 0,'flow_gutter')
    return os.path.dirname(input_dem)+'/flow_gutter.tif'

def flowsheds(input_dem):

    #open gutter with flow accumulation
    with rasterio.open(input_dem) as src:
        transform=src.transform
        band=np.array(src.read(1))
    im=img_as_float(band)
    nan=np.where(np.isnan(im))
    #set nan to zero
    im[nan]=0
    #calculate maxima
    coordinates = peak_local_max(im, min_distance=4)
    #transform maxima to (flowaccumulation,coordinates)
    new_coord=[]
    dtype=[('flowaccumulation',float),('coordinates',np.float64, (2,))]
    for coord in coordinates:
        new_coord.append((im[coord[0]][coord[1]],(transform[0]+(coord[1]+1)*transform[1]-transform[1]/2,transform[3]+coord[0]*transform[-1]-transform[1]/2)))
    new_coord=np.array(new_coord,dtype=dtype)
    #sort array  by flowaccumulation
    new_coord=np.sort(new_coord, order='flowaccumulation')
    #reverse array
    new_coord=new_coord[::-1]

    with fiona.open(os.path.dirname(input_dem)+ '/P_glac.shp', "w", "ESRI Shapefile",{'geometry': 'MultiPolygon', 'properties': {'flow_acc': 'float','id':'int'}}, crs) as p_glac:

        #for each pour point: create shapefile and run delinate watershed
        with fiona.open(os.path.dirname(input_dem)+'/all_watershed.shp', "w", "ESRI Shapefile", {'geometry': 'MultiPolygon', 'properties': {'flow_acc':'float','id':'int'}}, crs) as all_watershed:
            i = 0
            m = len(new_coord)
            print m
            while len(new_coord) is not 0:
                #create directory
                dir=os.path.dirname(input_dem)+'/'+str(i)
                if not os.path.isdir(dir):
                    os.makedirs(dir)

                coord=new_coord[0]
                #remove first element
                new_coord=new_coord[1:]
                #create radius around PPs and clip with outlines
                area=({'properties': {'flow_acc': coord['flowaccumulation'],'id':i},'geometry': mapping(shape(outlines['geometry']).intersection(shape(Point(coord['coordinates']).buffer(p_glac_radius(14.3,0.5,coord['flowaccumulation'])))))})
                #if result is Polygon, add it to shapefile
                if area['geometry']['type'] is 'Polygon':
                    p_glac.write(area)
                    #all_pourP.write({'properties': {'flow_acc': coord['flowaccumulation'], 'id': i,'p_glac': len(area['geometry']['coordinates'])},'geometry': {'type': 'Point', 'coordinates': coord['coordinates']}})
                #if result is MultiPolygon, add only the polygon whose perimeter is closest to PP
                elif area['geometry']['type'] is 'MultiPolygon':
                    min_dist=[]
                    for j in shape(area['geometry']):
                        min_dist.append(shape(j).distance(Point(coord['coordinates'])))
                    area['geometry']=mapping(shape(area['geometry'])[np.argmin(min_dist)])
                    p_glac.write(area)

                # write shapefile with ONE pour_point for watershed (transform unicode to ascii, otherwise segmentation fault)
                with fiona.open(dir+'/pour_point.shp', "w", "ESRI Shapefile", {'geometry': 'Point', 'properties': {'flow_acc':'float'}}, {k.encode('ascii'): v for k, v in crs.items()}) as output:
                    output.write({'properties': {'flow_acc':coord['flowaccumulation']},'geometry': {'type':'Point','coordinates':coord['coordinates']}})

                #calculate watershed for pour point
                routing.delineate_watershed(os.path.dirname(input_dem)+'/gutter2.tif',dir+'/pour_point.shp',0,100, dir+'/watershed_out.shp', dir+'/snapped_outlet_points_uri.shp', dir+'/stream_out_uri.tif')

                #add watershed polygon to watershed_all.shp
                with fiona.open(dir+'/watershed_out.shp', "r", "ESRI Shapefile") as watershed:
                    w=watershed.next()
                #cut watershed with outlines
                w['geometry']=mapping(shape(outlines['geometry']).intersection(shape(w['geometry']).buffer(0)))
                w['properties']['id']=i

                if w['geometry']['type'] is 'Polygon':
                    all_watershed.write(w)
                if w['geometry']['type'] is 'MultiPolygon':
                    #find polygon with minimal distance to pour point
                    dist=[]
                    for k in shape(w['geometry']):
                        dist.append(shape(k).distance(Point(coord['coordinates'])))
                    #add each polygon to all_watershed.shp
                    n=0
                    for l in shape(w['geometry']):
                        w['geometry'] =mapping(shape(l))
                        #polygon nearest to PP get current id
                        if n == np.argmin(dist):
                            w['properties']['id'] = i
                        # all other poylgons get new id
                        else:
                            m=m+1
                            w['properties']['id']=m
                        all_watershed.write(w)
                        n=n+1

                shutil.rmtree(dir)

                i=i+1
    return [os.path.dirname(input_dem)+ '/P_glac.shp',os.path.dirname(input_dem)+'/all_watershed.shp',m]

def gutter(masked_dem, depth):

    gutter_shp = os.path.dirname(masked_dem) + '/gutter.shp'

    with fiona.open(gutter_shp, "w", "ESRI Shapefile", schema, crs) as output:
        output.write({'properties': outlines['properties'],'geometry': mapping(shape(outlines['geometry']).buffer(pixelsize*2).difference(shape(outlines['geometry']).buffer(pixelsize)))})
    gutter_dem = clip(masked_dem, gutter_shp,0, 'gutter')
    gutter2_dem=os.path.dirname(gutter_dem)+'/gutter2.tif'
    with rasterio.open(masked_dem) as src1:
        mask_band = np.array(src1.read(1))
        with rasterio.open(gutter_dem) as src:
            mask_band = np.float32(mask_band - depth * (~np.isnan(np.array(src.read(1)))))
        with rasterio.open(gutter2_dem, "w", **src.meta.copy()) as dest:
            dest.write_band(1, mask_band)
    return gutter2_dem

def merge_flowsheds(P_glac_dir,watershed_dir):
    import time
    start=time.time()

    sliver_poly=[]
    watershed=[]
    glacier_poly={}
    total_glacier=MultiPolygon()
    P_poly=MultiPolygon()
    glacier_n=0

    #determinde overlaps from P_glac with watershed
    with fiona.open(watershed_dir, "r") as watersheds:
        for shed in watersheds:
            if not shape(shed['geometry']).is_valid:
                shed['geometry'] = shape(shed['geometry']).buffer(0)
            watershed.append(shape(shed['geometry']))

    with fiona.open(P_glac_dir, "r") as P_glac:
        for P in P_glac:
            P_poly=P_poly.union(shape(P['geometry']))
            to_merge=[]
            for i,shed in enumerate(watershed):
                if shape(P['geometry']).intersects(shed):
                    to_merge.append(i)
                    watershed[to_merge[0]]=shape(watershed[to_merge[0]]).union(shed)
                    if watershed[to_merge[0]].type not in ['Polygon','MultiPolygon']:
                        new=MultiPolygon()
                        for g in watershed[to_merge[0]]:
                            if g.type in ['Polygon','MultiPolygon']:
                                new=new.union(g)
                        watershed[to_merge[0]]=new
            for shed in [watershed[x] for x in to_merge[1::]]:
                watershed.remove(shed)

    #check for sliverpolygons
    while len(watershed) is not 0:
        shed=watershed.pop()
        if shed.type != 'Polygon':
            for pol in shed[1::]:
                #if pol.type is 'Polygon':
                watershed.append(pol)
            shed=shed[0]
        if shed.area < 100000 or (shed.area < 200000 and compactness(shed)):
            sliver_poly.append(shed)
        else:
            glacier_poly.update({'glacier' + str(glacier_n): shed})
            glacier_n = glacier_n + 1
            total_glacier=total_glacier.union(shed)
    print len(glacier_poly), len(sliver_poly)
    if shape(outlines['geometry']).difference(total_glacier.buffer(0.01)).buffer(-0.2).type == 'Polygon':
        sliver_poly.append(shape(outlines['geometry']).difference(total_glacier.buffer(0.01)).buffer(-0.2).buffer(0.3))
    else:
        for gap in shape(outlines['geometry']).difference(total_glacier.buffer(0.01)).buffer(-0.2):
            sliver_poly.append(gap.buffer(0.3))

    for polygon in sliver_poly:
        glacier_poly = merge_sliver_poly(glacier_poly, polygon)

    with fiona.open(os.path.dirname(P_glac_dir) + '/glaciers.shp', "w", "ESRI Shapefile", schema, crs) as test:
        for g in glacier_poly:
            out = outlines['properties']
            out['Name'] = g
            test.write({'properties': out, 'geometry': mapping(glacier_poly[g])})

    from itertools import combinations
    inter = [[pair[0], pair[1]] for pair in combinations(glacier_poly.keys(), 2)]
    while len(inter) is not 0:

        key = inter.pop(0)
        if key[0] is not key[1]:
            intersection = (glacier_poly[key[0]].buffer(0)).intersection(glacier_poly[key[1]].buffer(0))
            if intersection.type in ['Polygon', 'MultiPolygon', 'GeometryCollection']:
                if intersection.type in ['GeometryCollection']:
                    poly = MultiPolygon()
                    for polygon in intersection:
                        if polygon.type in ['Polygon', 'Mulltipolygon']:
                            poly = poly.union(polygon)
                    intersection = poly
                if intersection.area / shape(glacier_poly[key[0]]).area > 0.5 or intersection.area / shape(
                        glacier_poly[key[1]]).area > 0.5:
                    # union of both glaciers
                    glacier_poly[key[0]] = shape(glacier_poly[key[0]]).union(glacier_poly[key[1]])
                    # delete 2nd glacier
                    for i, tupel in enumerate(inter):

                        if key[1] in tupel:
                            if tupel[0] is not tupel[1]:
                                inter[i].append(key[0])
                                inter[i].remove(key[1])

                    del glacier_poly[key[1]]
                elif shape(glacier_poly[key[0]]).area > shape(glacier_poly[key[1]]).area:
                    glacier_poly[key[1]] = (shape(glacier_poly[key[1]]).difference(glacier_poly[key[0]])).buffer(-0.1).buffer(0.1)
                    if glacier_poly[key[1]].type is 'MultiPolygon':
                        poly_max = Polygon()
                        for poly in glacier_poly[key[1]]:
                            if poly.area > poly_max.area:
                                if not poly_max.is_empty:
                                    glacier_poly[key[1]] = shape(glacier_poly[key[1]]).difference(poly_max)
                                    glacier_poly = merge_sliver_poly(glacier_poly, poly_max.buffer(0.1))
                                poly_max = poly
                            else:
                                glacier_poly[key[1]] = shape(glacier_poly[key[1]]).difference(poly)
                                glacier_poly = merge_sliver_poly(glacier_poly, poly.buffer(0.1))

                else:
                    glacier_poly[key[0]] = (shape(glacier_poly[key[0]].buffer(0)).difference(glacier_poly[key[1]])).buffer(-0.1).buffer(0.1)
                    # print glacier_poly[key[1]].type
                    if glacier_poly[key[0]].type is 'MultiPolygon':
                        poly_max = Polygon()
                        for poly in glacier_poly[key[0]]:
                            if poly.area > poly_max.area:
                                if not poly_max.is_empty:
                                    glacier_poly[key[0]] = shape(glacier_poly[key[0]]).difference(poly_max)
                                    glacier_poly = merge_sliver_poly(glacier_poly, poly_max.buffer(0.1))
                                poly_max = poly
                            else:
                                glacier_poly[key[0]] = shape(glacier_poly[key[0]]).difference(poly)
                                # print shape(glacier_poly[key[1]]).intersection(poly.buffer(0.1))
                                glacier_poly = merge_sliver_poly(glacier_poly, poly.buffer(0.1))
                                # print key[0] ,glacier_poly[key[0]].type, key[1], glacier_poly[key[1]].type

    # check if final_glaciers are not sliver polygon:
    keys = glacier_poly.keys()
    for glac_id in keys:
        glac = glacier_poly[glac_id]
        if glac.area < 100000 or (glac.area < 200000 and compactness(glac)):
            del glacier_poly[glac_id]
            glacier_poly = merge_sliver_poly(glacier_poly, glac)


    i = 1
    k = True
    for P in P_poly:
        no_merge = []
        for name in glacier_poly:
            if P.intersects(glacier_poly[name]):
                no_merge.append(name)
        if len(no_merge) >1:
            glacier_poly[no_merge[0]] =cascaded_union([glacier_poly[x].buffer(0.1) for x in no_merge])
        for glacier in no_merge[1::]:
            glacier_poly.pop(glacier)

    for pol in glacier_poly:

        if not os.path.isdir(os.path.dirname(P_glac_dir) + '/divide_' + str(i).zfill(2)):
            os.mkdir(os.path.dirname(P_glac_dir) + '/divide_' + str(i).zfill(2))
        with fiona.open(os.path.dirname(P_glac_dir) + '/divide_' + str(i).zfill(2) + '/outlines.shp', "w",
                        "ESRI Shapefile", schema, crs) as gla:
            # for pol in glacier_poly
            if 'AREA' in schema['properties'].keys():
                outlines['properties']['AREA'] = glacier_poly[pol].area / 1000000
            elif 'Area' in schema['properties'].keys():
                outlines['properties']['Area'] = glacier_poly[pol].area / 1000000
            if glacier_poly[pol].type != 'Polygon':
                k = False
            gla.write({'properties': outlines['properties'], 'geometry': mapping(glacier_poly[pol])})
        i = i + 1
    print time.time()-start
    return i - 1, k
'''
def merge_flowsheds(P_glac_dir,watershed_dir,m):
    import time
    start=time.time()

    pp_merged={}
    all_poly_glac={}

    #determinde overlaps from P_glac with watershed
    with fiona.open(watershed_dir,"r") as watersheds:
        global crs
        crs=watersheds.crs
        silver_poly_check={}
        watershed_out=Polygon()
        for shed in watersheds:
            if not shape(shed['geometry']).is_valid:
                shed['geometry']=shape(shed['geometry']).buffer(0)
            watershed_out=watershed_out.union(shape(shed['geometry']))
            shed_status=False
            with fiona.open(P_glac_dir, "r") as P_glac:
                for P in P_glac:
                    if shape(P['geometry']).intersects(shape(shed['geometry'])):
                        shed_status=True
                        if 'PP_'+str(P['properties']['id']) in pp_merged:
                            pp_merged['PP_'+str(P['properties']['id'])]=pp_merged['PP_'+str(P['properties']['id'])].union({shed['properties']['id']})
                            all_poly_glac['PP_'+str(P['properties']['id'])] = all_poly_glac['PP_'+str(P['properties']['id'])].union(shape(shed['geometry']))
                        else:
                            pp_merged.update({'PP_'+str(P['properties']['id']):{shed['properties']['id']}})
                            all_poly_glac.update({'PP_'+str(P['properties']['id']):shape(shed['geometry'])})
                        #print all_poly_glac['PP_'+str(P['properties']['id'])].type
            #if shed don't overlay with any P_glac
            if shed_status is False :
                if shape(shed['geometry']).type =='MultiPolygon':
                    for poly in shape(shed['geometry']):
                        silver_poly_check.update({m: shape(poly)})
                        m=m+1
                else:
                    silver_poly_check.update({shed['properties']['id']:shape(shed['geometry'])})


    #merge P_glac-overlaps together
    glacier_n=0
    glacier_id={}
    glacier_poly={}
    for PP in pp_merged:
        pp_status=False

        if all_poly_glac[PP].type == 'MultiPolygon':
            p=Polygon()
            max_area=0
            for pol in all_poly_glac[PP]:
                if pol.area > max_area:
                    if not max_area == 0:
                        m=m+1
                        print m,p.area
                        silver_poly_check.update({m:p})
                    p=pol
                    max_area=p.area
                else:
                    m = m + 1
                    silver_poly_check.update({m: p})
            all_poly_glac[PP]=p

        for glac in glacier_id:
            if len(pp_merged[PP].intersection(glacier_id[glac])) is not 0 and all_poly_glac[PP].union(shape(glacier_poly[glac])).type =='Polygon':
                glacier_id[glac]=pp_merged[PP].union(glacier_id[glac])
                glacier_poly[glac] = all_poly_glac[PP].union(shape(glacier_poly[glac]))
                pp_status=True
        if not pp_status and len(pp_merged[PP])>1:
            glacier_id.update({'glacier'+str(glacier_n):pp_merged[PP]})
            glacier_poly.update({'glacier' + str(glacier_n): all_poly_glac[PP]})
            glacier_n=glacier_n+1
        if not pp_status and len(pp_merged[PP])==1:
            silver_poly_check.update({pp_merged[PP].pop():all_poly_glac[PP]})
    #check for sliver_polygons
    for polygon_id,polygon in silver_poly_check.iteritems():
        if polygon.area < 100000 or (polygon.area < 200000 and compactness(polygon)):
            glacier_poly=merge_sliver_poly(glacier_poly,polygon)

        else:
            print polygon_id,polygon.area
            glacier_id.update({'glacier'+str(glacier_n):{polygon_id}})
            glacier_poly.update({'glacier' + str(glacier_n): polygon})
            glacier_n=glacier_n+1

    #add regions, where no watersheds exists to glaciers   --> these are watersheds from pour points inside the glacier region
    #TODO: --> fill pits at DEM should avoid this, but function in pygeoprocessing is not working yet
    total_glacier=MultiPolygon()
    for glacier in glacier_poly:
        total_glacier=shape(total_glacier).union(shape(glacier_poly[glacier]))

    for polygon in shape(outlines['geometry']).difference(total_glacier.buffer(0.01)).buffer(-0.2):
        glacier_poly=merge_sliver_poly(glacier_poly,polygon.buffer(0.3))
    with fiona.open(os.path.dirname(P_glac_dir) + '/glaciers.shp', "w", "ESRI Shapefile",schema, crs) as glac:
        for g in glacier_poly:
            out=outlines['properties']
            out['Name']=g
            glac.write({'properties': out, 'geometry': mapping(glacier_poly[g])})

    #repair overlapping glaciers
    from itertools import combinations
    inter=[[pair[0],pair[1]] for pair in combinations(glacier_poly.keys(),2)]
    while len(inter) is not 0:

        key=inter.pop(0)
        if key[0] is not key[1]:
            intersection=(glacier_poly[key[0]].buffer(0)).intersection(glacier_poly[key[1]].buffer(0))
            if intersection.type in ['Polygon','MultiPolygon','GeometryCollection'] :
                if intersection.type in ['GeometryCollection']:
                    poly = MultiPolygon()
                    for polygon in intersection:
                        if polygon.type in ['Polygon', 'Mulltipolygon']:
                            poly = poly.union(polygon)
                    intersection=poly
                if intersection.area / shape(glacier_poly[key[0]]).area > 0.5 or intersection.area / shape(glacier_poly[key[1]]).area > 0.5:
                    #union of both glaciers
                    glacier_poly[key[0]]=shape(glacier_poly[key[0]]).union(glacier_poly[key[1]])
                    # delete 2nd glacier
                    for i,tupel in enumerate(inter):

                        if key[1] in tupel:
                            if tupel[0] is not tupel[1]:
                                inter[i].append(key[0])
                                inter[i].remove(key[1])

                    del glacier_poly[key[1]]
                elif shape(glacier_poly[key[0]]).area > shape(glacier_poly[key[1]]).area:
                    glacier_poly[key[1]] = (shape(glacier_poly[key[1]]).difference(glacier_poly[key[0]]))
                    if glacier_poly[key[1]].type is 'MultiPolygon':
                        poly_max = Polygon()
                        for poly in glacier_poly[key[1]]:
                            if poly.area > poly_max.area:
                                if not poly_max.is_empty:
                                    glacier_poly[key[1]] = shape(glacier_poly[key[1]]).difference(poly_max)
                                    glacier_poly=merge_sliver_poly(glacier_poly, poly_max.buffer(0.1))
                                poly_max = poly
                            else:
                                glacier_poly[key[1]] = shape(glacier_poly[key[1]]).difference(poly)
                                glacier_poly =merge_sliver_poly(glacier_poly, poly.buffer(0.1))

                else:
                    glacier_poly[key[0]] = (shape(glacier_poly[key[0]].buffer(0)).difference(glacier_poly[key[1]]))
                    #print glacier_poly[key[1]].type
                    if glacier_poly[key[0]].type is 'MultiPolygon':
                        poly_max=Polygon()
                        for poly in glacier_poly[key[0]]:
                            if poly.area>poly_max.area:
                                if not poly_max.is_empty :
                                    glacier_poly[key[0]] = shape(glacier_poly[key[0]]).difference(poly_max)
                                    glacier_poly =merge_sliver_poly(glacier_poly, poly_max.buffer(0.1))
                                poly_max=poly
                            else:
                                glacier_poly[key[0]] = shape(glacier_poly[key[0]]).difference(poly)
                                #print shape(glacier_poly[key[1]]).intersection(poly.buffer(0.1))
                                glacier_poly =merge_sliver_poly(glacier_poly, poly.buffer(0.1))
                        #print key[0] ,glacier_poly[key[0]].type, key[1], glacier_poly[key[1]].type

    #check if final_glaciers are not sliver polygon:
    keys=glacier_poly.keys()
    for glac_id in keys:
        glac=glacier_poly[glac_id]
        if glac.area < 100000 or (glac.area < 200000 and compactness(glac)):
            del glacier_poly[glac_id]
            glacier_poly=merge_sliver_poly(glacier_poly,glac)
    i=1
    k=True
    for pol in glacier_poly:

        if not os.path.isdir(os.path.dirname(P_glac_dir)+'/divide_'+str(i).zfill(2)):
            os.mkdir(os.path.dirname(P_glac_dir)+'/divide_'+str(i).zfill(2))
        with fiona.open(os.path.dirname(P_glac_dir)+'/divide_'+str(i).zfill(2)+'/outlines.shp',"w", "ESRI Shapefile",schema, crs) as gla:
            #for pol in glacier_poly
            if 'AREA' in schema['properties'].keys():
                outlines['properties']['AREA']=glacier_poly[pol].area/1000000
            elif 'Area' in schema['properties'].keys() :
                outlines['properties']['Area'] = glacier_poly[pol].area / 1000000
            if glacier_poly[pol].type != 'Polygon':
                k=False
            gla.write({'properties': outlines['properties'],'geometry': mapping(glacier_poly[pol])})
        i=i+1
    print time.time()-start
    return i-1,k
'''
def merge_sliver_poly(glacier_poly,polygon):
    max_boundary = 0
    max_boundary_id = -1
    for i, glac in glacier_poly.iteritems():
        if polygon.boundary.intersection(glac).length > max_boundary:
            max_boundary_id = i
            max_boundary = polygon.boundary.intersection(glac).length
    if not max_boundary_id == -1:
        glacier_poly[max_boundary_id] = glacier_poly[max_boundary_id].union(shape(polygon))
    return glacier_poly

def p_glac_radius(a, b, F):
    #test


    if a * (F ** b) +(pixelsize-40)*1.5 < 3500:
        return a * (F ** b) +(pixelsize-40)*1.5
    else:
        return 3500
    '''
    if a * (F ** b)*(float(pixelsize)/40) < 3500:
        return a * (F ** b)*(float(pixelsize)/40)
    else:
        return 3500
   '''

def dividing_glaciers(input_dem,input_shp):
    #*************************************************** preprocessing *************************************************
    #read outlines.shp
    global outlines
    global crs
    global schema
    with fiona.open(input_shp,'r') as shapefile:
        outlines=shapefile.next()
        crs=shapefile.crs
        print crs
        schema=shapefile.schema
        if not shape(outlines['geometry']).is_valid:
            outlines['geometry']=shape(outlines['geometry']).buffer(0)

    # get pixel size
    with rasterio.open(input_dem) as dem:
        global pixelsize
        pixelsize = int(dem.transform[1])

    #clip dem along buffer1
    masked_dem=clip(input_dem,input_shp,4*pixelsize,'masked')
    #create gutter
    gutter_dem=gutter(masked_dem,100)

    #****************************** Identification of pour points and flowshed calculation *****************************
    flow_gutter = flowacc(gutter_dem)
    # flowshed calculation
    [P_glac, watersheds,m] = flowsheds(flow_gutter)

    #*************** Allocation of flowsheds to individual glaciers & Identification of sliver polygons ****************
    no_glaciers,all_polygon=merge_flowsheds(P_glac, watersheds)

    # delete files which are not needed anymore
    for file in os.listdir(os.path.dirname(input_shp)):
        for word in []: #['P_glac','flow', 'gutter', 'masked']:
            if file.startswith(word):
                os.remove(os.path.dirname(input_shp) + '/' + file)
    return no_glaciers,all_polygon


if __name__ == '__main__':
    import time
    import shutil

    start0=time.time()
    #base_dir = '/home/juliaeis/Dokumente/OGGM/work_dir/CentralEurope/2000-3000'
    base_dir='E:\\partitioning\\CentralEurope\\2000-3000'

    for dir in os.listdir(base_dir+'/per_glacier'):
        if dir.startswith('RGI50-11.03728'):
        #if dir in ['RGI50-11.01144','RGI50-11.02460','RGI50-11.02755']:

            ###################preprocessing########################
            input_shp =base_dir+'/per_glacier/'+dir+'/outlines.shp'
            input_dem=os.path.dirname(input_shp)+'/dem.tif'
            input2_dem=os.path.dirname(input_shp)+'/dem2.tif'
            os.system('gdalwarp -tr 40 40 -r cubicspline -overwrite ' + input_dem + ' ' + input2_dem)
            for fol in os.listdir(os.path.dirname(input_shp)):
                if fol.startswith('divide'):
                    shutil.rmtree(os.path.dirname(input_shp)+'/'+fol)
            os.makedirs(base_dir+'/per_glacier/'+dir+'/divide_01')
            for file in [input_shp,os.path.dirname(input_shp)+'/outlines.shx',os.path.dirname(input_shp)+'/outlines.dbf']:
                shutil.copy(file,os.path.dirname(input_shp)+'/divide_01')

            n,k=dividing_glaciers(input2_dem, input_shp)